from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import MAX_CENTS
from app.domain.accounts.access import use_account, visible_account
from app.domain.accounts.models import Account
from app.domain.audit import audit, snap
from app.domain.cards.models import CreditCard
from app.domain.errors import DomainError
from app.domain.goals.models import GoalAccount
from app.domain.loans.models import Loan
from app.domain.pockets.models import Pocket
from app.domain.spaces.access import require_member, require_owner
from app.domain.spaces.models import SpaceMember
from app.domain.transactions.models import Transaction

ACCOUNT_TYPES = {"checking", "wallet", "savings"}


async def create_account(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, name: str,
    initial_balance_cents: int = 0, institution: str | None = None, opened_on: date | None = None,
) -> Account:  # fmt: skip
    await require_member(session, actor_id, space_id)
    if type not in ACCOUNT_TYPES:
        raise DomainError("invalid_account_type")
    if abs(initial_balance_cents) > MAX_CENTS:
        raise DomainError("amount_too_large")
    acc = Account(
        space_id=space_id,
        type=type,
        name=name,
        initial_balance_cents=initial_balance_cents,
        institution=institution,
        opened_on=opened_on,
    )
    session.add(acc)
    await session.flush()
    audit(
        session,
        actor_id,
        "account.create",
        "account",
        acc.id,
        {"space_id": str(space_id), "type": type},
    )
    await session.commit()
    return acc


async def set_default_account(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, account_id: UUID
) -> None:
    member = await require_member(session, actor_id, space_id)
    await use_account(session, actor_id, account_id)  # pode ser conta de outro espaço seu
    member.default_account_id = account_id
    audit(session, actor_id, "account.set_default", "account", account_id,
          {"space_id": str(space_id)})  # fmt: skip
    await session.commit()


async def update_account(
    session: AsyncSession, *, actor_id: UUID, account_id: UUID, fields: dict[str, Any]
) -> Account:
    """fields: só as chaves enviadas (name, initial_balance_cents, institution)."""
    acc = await visible_account(session, actor_id, account_id)
    await require_owner(session, actor_id, acc.space_id)
    before = snap(acc, fields)
    if "name" in fields:
        acc.name = fields["name"]
    if "institution" in fields:
        acc.institution = fields["institution"]
    if "initial_balance_cents" in fields:
        if abs(fields["initial_balance_cents"]) > MAX_CENTS:
            raise DomainError("amount_too_large")
        acc.initial_balance_cents = fields["initial_balance_cents"]
    audit(session, actor_id, "account.update", "account", acc.id,
          {"space_id": str(acc.space_id), "before": before,
           "after": snap(acc, fields)})  # fmt: skip
    await session.commit()
    return acc


async def delete_account(session: AsyncSession, *, actor_id: UUID, account_id: UUID) -> None:
    """Só o dono do espaço; recusa conta com lançamentos, cartão ou meta ligados (sem arquivar)."""
    acc = await visible_account(session, actor_id, account_id)
    await require_owner(session, actor_id, acc.space_id)
    used = await session.scalar(
        select(
            exists().where(
                or_(Transaction.account_id == acc.id, Transaction.counter_account_id == acc.id)
            )
            | exists().where(CreditCard.payment_account_id == acc.id)
            | exists().where(GoalAccount.account_id == acc.id)
            | exists().where(Pocket.account_id == acc.id)
            | exists().where(Loan.account_id == acc.id)
        )
    )
    if used:
        raise DomainError("account_in_use")
    await session.execute(
        update(SpaceMember)
        .where(SpaceMember.default_account_id == acc.id)
        .values(default_account_id=None)
    )
    audit(session, actor_id, "account.delete", "account", acc.id, {"space_id": str(acc.space_id)})
    await session.delete(acc)
    await session.commit()

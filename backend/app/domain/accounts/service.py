from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.access import use_account
from app.domain.accounts.models import Account
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member

ACCOUNT_TYPES = {"checking", "wallet", "savings"}


async def create_account(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, name: str,
    initial_balance_cents: int = 0,
) -> Account:  # fmt: skip
    await require_member(session, actor_id, space_id)
    if type not in ACCOUNT_TYPES:
        raise DomainError("invalid_account_type")
    acc = Account(
        space_id=space_id, type=type, name=name, initial_balance_cents=initial_balance_cents
    )
    session.add(acc)
    await session.commit()
    return acc


async def set_default_account(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, account_id: UUID
) -> None:
    member = await require_member(session, actor_id, space_id)
    await use_account(session, actor_id, account_id)  # pode ser conta de outro espaço seu
    member.default_account_id = account_id
    await session.commit()

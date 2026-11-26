from dataclasses import asdict
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, Session
from app.api.schemas import AccountDetailOut, AccountOut, AccountPanelOut, SignedCents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.accounts.access import visible_account
from app.domain.accounts.models import Account
from app.domain.accounts.panel import account_panel
from app.domain.accounts.service import (
    create_account,
    delete_account,
    set_default_account,
    update_account,
)
from app.domain.accounts.statement import account_statement
from app.domain.errors import DomainError
from app.domain.pockets.service import account_pockets_cents
from app.domain.spaces.models import SpaceMember
from app.domain.transactions.service import account_balance

router = APIRouter(tags=["accounts"])

Institution = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]


async def _out(session: AsyncSession, acc: Account) -> dict[str, Any]:
    balance = await account_balance(session, acc.id)
    pockets = await account_pockets_cents(session, acc.id)
    return row(acc) | {
        "balance_cents": balance, "pockets_cents": pockets, "available_cents": balance - pockets
    }  # fmt: skip


class AccountIn(BaseModel):
    type: Literal["checking", "wallet", "savings"]
    name: str = Field(min_length=1, max_length=100)
    initial_balance_cents: SignedCents = 0
    institution: Institution | None = None


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    initial_balance_cents: SignedCents | None = None
    institution: Institution | None = None  # null remove o banco


class DefaultAccountIn(BaseModel):
    account_id: UUID


@router.post("/spaces/{space_id}/accounts", status_code=201, response_model=AccountOut)
async def create(
    space_id: UUID, body: AccountIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    acc = await create_account(
        session, actor_id=user.id, space_id=space_id, type=body.type, name=body.name,
        initial_balance_cents=body.initial_balance_cents, institution=body.institution,
        opened_on=local_today(user.tz),
    )  # fmt: skip
    return await _out(session, acc)


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    """Contas de todos os espaços de que o usuário é membro (inclui as compartilháveis)."""
    rows = await session.scalars(
        select(Account)
        .join(SpaceMember, SpaceMember.space_id == Account.space_id)
        .where(SpaceMember.user_id == user.id)
        .order_by(Account.name)
    )
    return [await _out(session, a) for a in rows]


@router.get("/accounts/{account_id}", response_model=AccountDetailOut)
async def get_account(account_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    acc = await visible_account(session, user.id, account_id)
    return await _out(session, acc)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def patch(
    account_id: UUID, body: AccountPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    fields = {
        k: v for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None or k == "institution"
    }  # fmt: skip
    acc = await update_account(session, actor_id=user.id, account_id=account_id, fields=fields)
    return await _out(session, acc)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete(account_id: UUID, user: CurrentUser, session: Session) -> None:
    await delete_account(session, actor_id=user.id, account_id=account_id)


@router.put("/spaces/{space_id}/default-account", status_code=204)
async def default_account(
    space_id: UUID, body: DefaultAccountIn, user: CurrentUser, session: Session
) -> None:
    await set_default_account(
        session, actor_id=user.id, space_id=space_id, account_id=body.account_id
    )


@router.get("/accounts/{account_id}/panel", response_model=AccountPanelOut)
async def panel(
    account_id: UUID, user: CurrentUser, session: Session,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> dict[str, Any]:  # fmt: skip
    today = local_today(user.tz)
    first = date(int(month[:4]), int(month[5:]), 1) if month else today.replace(day=1)
    return await account_panel(session, user.id, account_id, month=first, today=today)


@router.get("/accounts/{account_id}/statement")
async def statement(
    account_id: UUID, start: date, end: date, user: CurrentUser, session: Session
) -> dict[str, Any]:
    if not 0 <= (end - start).days <= 366:
        raise DomainError("invalid_date_range")
    return asdict(await account_statement(session, user.id, account_id, start, end))

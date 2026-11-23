from dataclasses import asdict
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.schemas import SignedCents
from app.core.serialize import row
from app.domain.accounts.access import visible_account
from app.domain.accounts.models import Account
from app.domain.accounts.service import create_account, set_default_account
from app.domain.accounts.statement import account_statement
from app.domain.errors import DomainError
from app.domain.spaces.models import SpaceMember
from app.domain.transactions.service import account_balance

router = APIRouter(tags=["accounts"])


class AccountIn(BaseModel):
    type: Literal["checking", "wallet", "savings"]
    name: str = Field(min_length=1, max_length=100)
    initial_balance_cents: SignedCents = 0


class DefaultAccountIn(BaseModel):
    account_id: UUID


@router.post("/spaces/{space_id}/accounts", status_code=201)
async def create(
    space_id: UUID, body: AccountIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    acc = await create_account(
        session, actor_id=user.id, space_id=space_id, type=body.type, name=body.name,
        initial_balance_cents=body.initial_balance_cents,
    )  # fmt: skip
    return row(acc)


@router.get("/accounts")
async def list_accounts(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    """Contas de todos os espaços de que o usuário é membro (inclui as compartilháveis)."""
    rows = await session.scalars(
        select(Account)
        .join(SpaceMember, SpaceMember.space_id == Account.space_id)
        .where(SpaceMember.user_id == user.id)
        .order_by(Account.name)
    )
    return [row(a) for a in rows]


@router.get("/accounts/{account_id}")
async def get_account(account_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    acc = await visible_account(session, user.id, account_id)
    return row(acc) | {"balance_cents": await account_balance(session, acc.id)}


@router.put("/spaces/{space_id}/default-account", status_code=204)
async def default_account(
    space_id: UUID, body: DefaultAccountIn, user: CurrentUser, session: Session
) -> None:
    await set_default_account(
        session, actor_id=user.id, space_id=space_id, account_id=body.account_id
    )


@router.get("/accounts/{account_id}/statement")
async def statement(
    account_id: UUID, start: date, end: date, user: CurrentUser, session: Session
) -> dict[str, Any]:
    if not 0 <= (end - start).days <= 366:
        raise DomainError("invalid_date_range")
    return asdict(await account_statement(session, user.id, account_id, start, end))

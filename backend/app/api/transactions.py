from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.transactions.service import create_transaction, list_transactions

router = APIRouter(tags=["transactions"])


class TransactionIn(BaseModel):
    type: Literal["expense", "income", "transfer"]
    amount_cents: Cents
    occurred_on: date | None = None  # padrão: hoje no fuso do usuário
    description: str = Field(default="", max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    category_id: UUID | None = None
    account_id: UUID
    counter_account_id: UUID | None = None


@router.post("/spaces/{space_id}/transactions", status_code=201)
async def create(
    space_id: UUID, body: TransactionIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await create_transaction(
        session, actor_id=user.id, space_id=space_id, type=body.type,
        amount_cents=body.amount_cents, occurred_on=body.occurred_on or local_today(user.tz),
        description=body.description, merchant=body.merchant, category_id=body.category_id,
        account_id=body.account_id, counter_account_id=body.counter_account_id, origin="web",
    )  # fmt: skip
    return row(tx)


@router.get("/spaces/{space_id}/transactions")
async def list_(
    space_id: UUID, user: CurrentUser, session: Session,
    start: date | None = None, end: date | None = None, category_id: UUID | None = None,
    account_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:  # fmt: skip
    txs = await list_transactions(
        session, viewer_id=user.id, space_id=space_id, start=start, end=end,
        category_id=category_id, account_id=account_id, limit=limit, offset=offset,
    )  # fmt: skip
    return [row(t) for t in txs]

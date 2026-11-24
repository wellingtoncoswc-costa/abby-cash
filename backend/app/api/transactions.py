from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents, TransactionOut
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.transactions.service import (
    count_transactions,
    create_transaction,
    delete_transaction,
    list_transactions,
    update_transaction,
)

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


class TransactionPatch(BaseModel):
    amount_cents: Cents | None = None
    description: str | None = Field(default=None, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    category_id: UUID | None = None
    occurred_on: date | None = None


@router.post("/spaces/{space_id}/transactions", status_code=201, response_model=TransactionOut)
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


@router.get("/spaces/{space_id}/transactions", response_model=list[TransactionOut])
async def list_(
    space_id: UUID, user: CurrentUser, session: Session, response: Response,
    start: date | None = None, end: date | None = None, category_id: UUID | None = None,
    account_id: UUID | None = None, card_id: UUID | None = None, created_by: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:  # fmt: skip
    """Total (sem paginação) no cabeçalho X-Total-Count; o corpo segue sendo a lista."""
    f: dict[str, Any] = dict(start=start, end=end, category_id=category_id, account_id=account_id,
             card_id=card_id, created_by=created_by)  # fmt: skip
    txs = await list_transactions(
        session, viewer_id=user.id, space_id=space_id, limit=limit, offset=offset, **f
    )
    response.headers["X-Total-Count"] = str(
        await count_transactions(session, viewer_id=user.id, space_id=space_id, **f)
    )
    return [row(t) for t in txs]


@router.patch("/transactions/{tx_id}", response_model=TransactionOut)
async def patch(
    tx_id: UUID, body: TransactionPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    tx = await update_transaction(
        session, actor_id=user.id, tx_id=tx_id, **body.model_dump(exclude_unset=True)
    )
    return row(tx)


@router.delete("/transactions/{tx_id}", status_code=204)
async def delete(tx_id: UUID, user: CurrentUser, session: Session) -> None:
    """Parcelada: apaga o grupo todo."""
    await delete_transaction(session, actor_id=user.id, tx_id=tx_id)

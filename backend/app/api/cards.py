from dataclasses import asdict
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.schemas import CardOut, Cents, InvoiceDetailOut, InvoiceOut, TransactionOut
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.cards.models import CreditCard, Invoice
from app.domain.cards.service import (
    create_card,
    delete_card,
    invoice_statement,
    invoice_summary,
    register_card_purchase,
    update_card,
    visible_card,
    visible_invoice,
)
from app.domain.spaces.models import SpaceMember

router = APIRouter(tags=["cards"])
Day = Annotated[int, Field(strict=True, ge=1, le=31)]


class CardIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    closing_day: Day
    due_day: Day
    limit_cents: Cents | None = None
    payment_account_id: UUID | None = None


class PurchaseIn(BaseModel):
    card_id: UUID
    amount_cents: Cents
    installments: Annotated[int, Field(strict=True, ge=1, le=48)] = 1
    occurred_on: date | None = None  # padrão: hoje no fuso do usuário
    description: str = Field(default="", max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    category_id: UUID | None = None


@router.post("/spaces/{space_id}/cards", status_code=201, response_model=CardOut)
async def create(
    space_id: UUID, body: CardIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    card = await create_card(
        session, actor_id=user.id, space_id=space_id, name=body.name,
        closing_day=body.closing_day, due_day=body.due_day, limit_cents=body.limit_cents,
        payment_account_id=body.payment_account_id,
    )  # fmt: skip
    return row(card)


@router.get("/cards", response_model=list[CardOut])
async def list_cards(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(CreditCard)
        .join(SpaceMember, SpaceMember.space_id == CreditCard.space_id)
        .where(SpaceMember.user_id == user.id)
        .order_by(CreditCard.name)
    )
    return [row(c) for c in rows]


@router.post(
    "/spaces/{space_id}/card-purchases", status_code=201, response_model=list[TransactionOut]
)
async def purchase(
    space_id: UUID, body: PurchaseIn, user: CurrentUser, session: Session
) -> list[dict[str, Any]]:
    txs = await register_card_purchase(
        session, actor_id=user.id, space_id=space_id, card_id=body.card_id,
        amount_cents=body.amount_cents, occurred_on=body.occurred_on or local_today(user.tz),
        installments=body.installments, description=body.description, merchant=body.merchant,
        category_id=body.category_id, origin="web",
    )  # fmt: skip
    return [row(t) for t in txs]


@router.get("/cards/{card_id}/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    card_id: UUID, user: CurrentUser, session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> list[dict[str, Any]]:  # fmt: skip
    card = await visible_card(session, user.id, card_id)
    invs = await session.scalars(
        select(Invoice)
        .where(Invoice.card_id == card.id)
        .order_by(Invoice.closing_on.desc())
        .limit(limit)
    )
    return [row(i) | await invoice_summary(session, i) for i in invs]


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
async def get_invoice(invoice_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    inv, _ = await visible_invoice(session, user.id, invoice_id)
    stmt = await invoice_statement(session, user.id, invoice_id)
    return row(inv) | await invoice_summary(session, inv) | {"statement": asdict(stmt)}


class CardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    closing_day: Day | None = None
    due_day: Day | None = None
    limit_cents: Cents | None = None  # null remove o limite
    payment_account_id: UUID | None = None  # null remove a conta de pagamento


@router.patch("/cards/{card_id}", response_model=CardOut)
async def patch(
    card_id: UUID, body: CardPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    for k in ("name", "closing_day", "due_day"):
        if k in fields and fields[k] is None:
            del fields[k]
    return row(await update_card(session, actor_id=user.id, card_id=card_id, fields=fields))


@router.delete("/cards/{card_id}", status_code=204)
async def delete(card_id: UUID, user: CurrentUser, session: Session) -> None:
    await delete_card(session, actor_id=user.id, card_id=card_id)

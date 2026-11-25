from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import exists, select

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.errors import DomainError
from app.domain.investments import service as svc
from app.domain.investments.models import InvestmentMovement
from app.domain.spaces.access import require_owner

MIN_DATE, MAX_DATE = date(2000, 1, 1), date(2100, 12, 31)
router = APIRouter(tags=["investments"])


class InvestmentIn(BaseModel):
    kind: Literal["stock", "fii", "cdb", "lci", "lca"]
    name: str = Field(min_length=1, max_length=100)
    ticker: str | None = Field(default=None, max_length=12)
    rate_type: Literal["cdi_pct", "fixed"] | None = None
    rate_bp: int | None = Field(default=None, strict=True, ge=1, le=100_000)
    maturity_on: date | None = None


class MoveIn(BaseModel):
    account_id: UUID
    occurred_on: date | None = Field(default=None, ge=MIN_DATE, le=MAX_DATE)
    amount_cents: Cents | None = None  # renda fixa
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    unit_price_cents: Cents | None = None  # opcional: vence o preço do dia


class InvestmentOut(BaseModel):
    id: UUID
    space_id: UUID
    kind: str
    name: str
    ticker: str | None
    rate_type: str | None
    rate_bp: int | None
    maturity_on: date | None


class MovementOut(BaseModel):
    id: UUID
    investment_id: UUID
    kind: str
    occurred_on: date
    quantity: Decimal | None
    unit_price_cents: int | None
    amount_cents: int
    transaction_id: UUID


@router.post("/spaces/{space_id}/investments", status_code=201, response_model=InvestmentOut)
async def create(
    space_id: UUID, body: InvestmentIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    inv = await svc.create_investment(
        session, actor_id=user.id, space_id=space_id, today=local_today(user.tz),
        **body.model_dump(),
    )  # fmt: skip
    return row(inv)


@router.get("/spaces/{space_id}/investments/dashboard")
async def dashboard(space_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await svc.dashboard(
        session, viewer_id=user.id, space_id=space_id, today=local_today(user.tz)
    )


async def _move(
    fn: Any, investment_id: UUID, body: MoveIn, user: Any, session: Any
) -> dict[str, Any]:
    today = local_today(user.tz)
    mv = await fn(
        session, actor_id=user.id, investment_id=investment_id, account_id=body.account_id,
        on=body.occurred_on or today, amount_cents=body.amount_cents, quantity=body.quantity,
        unit_price_cents=body.unit_price_cents, today=today,
    )  # fmt: skip
    return row(mv)


@router.post("/investments/{investment_id}/buys", status_code=201, response_model=MovementOut)
async def add_buy(
    investment_id: UUID, body: MoveIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    return await _move(svc.buy, investment_id, body, user, session)


@router.post("/investments/{investment_id}/redeems", status_code=201, response_model=MovementOut)
async def add_redeem(
    investment_id: UUID, body: MoveIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    return await _move(svc.redeem, investment_id, body, user, session)


@router.delete("/investments/{investment_id}", status_code=204)
async def delete(investment_id: UUID, user: CurrentUser, session: Session) -> None:
    inv = await svc.visible_investment(session, user.id, investment_id, lock=True)
    await require_owner(session, user.id, inv.space_id)
    if await session.scalar(select(exists().where(InvestmentMovement.investment_id == inv.id))):
        raise DomainError("investment_has_history")
    await session.delete(inv)
    await session.commit()

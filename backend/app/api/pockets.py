from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.api.schemas import CdiLatestOut, Cents, PocketMovementOut, PocketOut
from app.core.config import get_settings
from app.core.dates import local_today
from app.core.serialize import row
from app.domain.pockets.cdi import annual_pct, latest_cdi
from app.domain.pockets.models import Pocket
from app.domain.pockets.service import (
    create_pocket,
    delete_pocket,
    deposit,
    list_movements,
    pocket_stats,
    update_pocket,
    visible_pocket,
    withdraw,
)
from app.domain.spaces.access import require_member

router = APIRouter(tags=["pockets"])
MIN_DATE, MAX_DATE = date(2000, 1, 1), date(2100, 12, 31)
CdiBp = Annotated[int, Field(strict=True, ge=1, le=100_000)]


class PocketIn(BaseModel):
    account_id: UUID
    name: str = Field(min_length=1, max_length=100)
    cdi_bp: CdiBp


class PocketPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    cdi_bp: CdiBp | None = None


class MoveIn(BaseModel):
    amount_cents: Cents
    occurred_on: date | None = Field(default=None, ge=MIN_DATE, le=MAX_DATE)


async def _out(session: Any, p: Pocket, today: date) -> dict[str, Any]:
    st = await pocket_stats(session, p.id, today)
    return row(p) | {
        "balance_cents": st.balance, "pending_yield_cents": st.pending,
        "month_yield_cents": st.month_yield,
    }  # fmt: skip


@router.post("/spaces/{space_id}/pockets", status_code=201, response_model=PocketOut)
async def create(
    space_id: UUID, body: PocketIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    p = await create_pocket(
        session, actor_id=user.id, space_id=space_id, account_id=body.account_id,
        name=body.name, cdi_bp=body.cdi_bp,
    )  # fmt: skip
    return await _out(session, p, local_today(get_settings().DEFAULT_TZ))


@router.get("/spaces/{space_id}/pockets", response_model=list[PocketOut])
async def list_(space_id: UUID, user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    await require_member(session, user.id, space_id)
    pockets = await session.scalars(
        select(Pocket)
        .where(Pocket.space_id == space_id, Pocket.closed_at.is_(None))
        .order_by(Pocket.created_at)
    )
    today = local_today(get_settings().DEFAULT_TZ)
    # ponytail: 3 queries por caixinha (N+1); ok para poucas caixinhas
    return [await _out(session, p, today) for p in pockets]


@router.patch("/pockets/{pocket_id}", response_model=PocketOut)
async def patch(
    pocket_id: UUID, body: PocketPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    p = await update_pocket(session, actor_id=user.id, pocket_id=pocket_id, fields=fields)
    return await _out(session, p, local_today(get_settings().DEFAULT_TZ))


@router.delete("/pockets/{pocket_id}", status_code=204)
async def delete(pocket_id: UUID, user: CurrentUser, session: Session) -> None:
    await delete_pocket(session, actor_id=user.id, pocket_id=pocket_id)


@router.post("/pockets/{pocket_id}/deposit", status_code=201, response_model=PocketOut)
async def add_deposit(
    pocket_id: UUID, body: MoveIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    today = local_today(get_settings().DEFAULT_TZ)
    await deposit(session, actor_id=user.id, pocket_id=pocket_id,
                  amount_cents=body.amount_cents, on=body.occurred_on or today)  # fmt: skip
    return await _out(session, await visible_pocket(session, user.id, pocket_id), today)


@router.post("/pockets/{pocket_id}/withdraw", status_code=201, response_model=PocketOut)
async def add_withdraw(
    pocket_id: UUID, body: MoveIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    today = local_today(get_settings().DEFAULT_TZ)
    await withdraw(session, actor_id=user.id, pocket_id=pocket_id,
                   amount_cents=body.amount_cents, on=body.occurred_on or today)  # fmt: skip
    return await _out(session, await visible_pocket(session, user.id, pocket_id), today)


@router.get("/pockets/{pocket_id}/movements", response_model=list[PocketMovementOut])
async def movements(pocket_id: UUID, user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    mvs = await list_movements(session, viewer_id=user.id, pocket_id=pocket_id)
    return [row(m) for m in mvs]


@router.get("/cdi/latest", response_model=CdiLatestOut)
async def cdi_latest(user: CurrentUser, session: Session) -> dict[str, Any]:
    r = await latest_cdi(session)
    if r is None:
        raise HTTPException(status_code=404, detail="cdi_unavailable")
    return {
        "on_date": r.on_date, "daily_pct": str(r.daily_pct),
        "annual_pct": f"{annual_pct(r.daily_pct):.4f}",
    }  # fmt: skip

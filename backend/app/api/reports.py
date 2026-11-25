from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, Session
from app.api.schemas import Out
from app.core.dates import local_today
from app.domain.reports.service import overview
from app.domain.transactions.service import Filters

router = APIRouter(tags=["reports"])
MAX_DAYS = 3660


class Totals(Out):
    income_cents: int
    expense_cents: int
    net_cents: int
    tx_count: int
    avg_daily_expense_cents: int


class ByCategory(Out):
    category_id: UUID | None
    name: str
    expense_cents: int
    count: int
    share_bp: int


class ByMerchant(Out):
    merchant: str
    expense_cents: int
    count: int


class ByAccount(Out):
    account_id: UUID | None
    name: str
    income_cents: int
    expense_cents: int


class ByDay(Out):
    date: date
    income_cents: int
    expense_cents: int


class ByMonth(Out):
    month: str
    income_cents: int
    expense_cents: int
    net_cents: int


class ByWeekday(Out):
    dow: int
    expense_cents: int
    count: int


class Largest(Out):
    id: UUID
    occurred_on: date
    description: str
    merchant: str | None
    category_id: UUID | None
    amount_cents: int
    type: str


class BalancePoint(Out):
    month: str
    balance_cents: int


class Upcoming(Out):
    kind: Literal["bill", "invoice"]
    id: UUID
    description: str
    due_on: date
    amount_cents: int


class OverviewOut(Out):
    totals: Totals
    previous: Totals
    by_category: list[ByCategory]
    by_merchant: list[ByMerchant]
    by_account: list[ByAccount]
    by_day: list[ByDay]
    by_month: list[ByMonth]
    by_weekday: list[ByWeekday]
    largest: list[Largest]
    balance_series: list[BalancePoint]
    upcoming: list[Upcoming]


@router.get("/spaces/{space_id}/reports/overview", response_model=OverviewOut)
async def get_overview(
    space_id: UUID, user: CurrentUser, session: Session, start: date, end: date,
    account_id: UUID | None = None, card_id: UUID | None = None,
    category_id: Annotated[str | None, Query(description="UUID ou 'none' (sem categoria)")] = None,
    merchant: str | None = None, type: Literal["expense", "income"] | None = None,
) -> dict[str, Any]:  # fmt: skip
    if start > end or (end - start).days >= MAX_DAYS:
        raise HTTPException(status_code=422, detail="invalid_range")
    cat: UUID | None = None
    if category_id not in (None, "none"):
        try:
            cat = UUID(str(category_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid_category") from None
    f = Filters(category_id=cat, uncategorized=category_id == "none", account_id=account_id,
                card_id=card_id, merchant=merchant, type=type)  # fmt: skip
    return await overview(
        session, viewer_id=user.id, space_id=space_id, start=start, end=end,
        today=local_today(user.tz), filters=f,
    )  # fmt: skip

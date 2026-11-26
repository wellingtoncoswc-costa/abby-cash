from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import Cents
from app.core.dates import local_today
from app.domain.bills.recurrence import Recurrence
from app.domain.recurring import service as svc

router = APIRouter(tags=["recurring"])
Day = Annotated[int, Field(strict=True, ge=1, le=31)]


class RuleIn(BaseModel):
    kind: Literal["monthly", "yearly", "every_n_months"]
    day: Day
    month: Annotated[int, Field(strict=True, ge=1, le=12)] | None = None  # só yearly
    n: Annotated[int, Field(strict=True, ge=1, le=120)] = 1  # só every_n_months

    def rule(self) -> Recurrence:
        return Recurrence(self.kind, self.day, month=self.month, n=self.n)


class RecurringIn(BaseModel):
    type: Literal["expense", "income"]
    description: str = Field(min_length=1, max_length=200)
    amount_cents: Cents
    account_id: UUID  # despesa: de onde sai; receita: onde entra
    category_id: UUID | None = None
    rule: RuleIn
    starts_on: date
    ends_on: date | None = None


class RecurringPatch(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=200)
    amount_cents: Cents | None = None
    account_id: UUID | None = None
    category_id: UUID | None = None
    rule: RuleIn | None = None
    ends_on: date | None = None  # null remove o fim
    active: bool | None = None


class RecurringOut(BaseModel):
    id: UUID
    space_id: UUID
    type: str
    description: str
    amount_cents: int
    account_id: UUID
    category_id: UUID | None
    rule: dict[str, Any]
    starts_on: date
    ends_on: date | None
    active: bool
    next_due_on: date | None


class ProjectionMonthOut(BaseModel):
    month: date
    income_cents: int
    expense_cents: int
    net_cents: int
    projected_balance_cents: int


class UpcomingOut(BaseModel):
    due_on: date
    description: str
    type: str
    amount_cents: int
    account_id: UUID
    account_name: str


class ProjectionOut(BaseModel):
    months: list[ProjectionMonthOut]
    upcoming: list[UpcomingOut]


def _out(item: Any, next_due_on: date | None) -> dict[str, Any]:
    cols = ("id space_id type description amount_cents account_id category_id rule starts_on "
            "ends_on active").split()  # fmt: skip
    return {c: getattr(item, c) for c in cols} | {"next_due_on": next_due_on}


@router.post("/spaces/{space_id}/recurring", status_code=201, response_model=RecurringOut)
async def create(
    space_id: UUID, body: RecurringIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    item = await svc.create_item(
        session, actor_id=user.id, space_id=space_id, type=body.type,
        description=body.description, amount_cents=body.amount_cents, account_id=body.account_id,
        category_id=body.category_id, rule=body.rule.rule(), starts_on=body.starts_on,
        ends_on=body.ends_on,
    )  # fmt: skip
    return _out(item, svc.next_due(item, local_today(user.tz)))


@router.get("/spaces/{space_id}/recurring", response_model=list[RecurringOut])
async def list_(space_id: UUID, user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await svc.list_items(
        session, viewer_id=user.id, space_id=space_id, today=local_today(user.tz)
    )
    return [_out(r["item"], r["next_due_on"]) for r in rows]


@router.get("/spaces/{space_id}/recurring/projection", response_model=ProjectionOut)
async def projection(space_id: UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await svc.projection(
        session, viewer_id=user.id, space_id=space_id, today=local_today(user.tz)
    )


@router.patch("/spaces/{space_id}/recurring/{item_id}", response_model=RecurringOut)
async def patch(
    space_id: UUID, item_id: UUID, body: RecurringPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    for k in ("description", "amount_cents", "account_id", "rule", "active"):
        if k in fields and fields[k] is None:
            del fields[k]
    if "rule" in fields:
        fields["rule"] = body.rule.rule()  # type: ignore[union-attr]
    item = await svc.update_item(
        session, actor_id=user.id, space_id=space_id, item_id=item_id, fields=fields
    )
    return _out(item, svc.next_due(item, local_today(user.tz)))


@router.delete("/spaces/{space_id}/recurring/{item_id}", status_code=204)
async def delete(space_id: UUID, item_id: UUID, user: CurrentUser, session: Session) -> None:
    await svc.delete_item(session, actor_id=user.id, space_id=space_id, item_id=item_id)

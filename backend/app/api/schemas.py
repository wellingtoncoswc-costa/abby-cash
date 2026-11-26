from datetime import date, datetime, time
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.money import MAX_CENTS

# int estrito: 45.5 e "4500" viram 422 (dinheiro nunca é float nem string)
Cents = Annotated[int, Field(strict=True, gt=0, le=MAX_CENTS)]
SignedCents = Annotated[int, Field(strict=True, ge=-MAX_CENTS, le=MAX_CENTS)]


class Out(BaseModel):
    """Modelos de resposta: nomes de campo iguais às colunas (amount_cents etc.)."""


class MeOut(Out):
    id: UUID
    name: str
    email: str
    tz: str
    default_space_id: UUID | None
    preferred_channel: str | None
    reminder_time: time
    weekly_digest: bool
    is_admin: bool
    totp_enabled: bool


class SpaceOut(Out):
    id: UUID
    type: str
    name: str


class MemberOut(Out):
    user_id: UUID
    name: str
    role: str
    joined_at: datetime


class CategoryOut(Out):
    id: UUID
    space_id: UUID
    kind: str
    name: str
    icon: str | None
    color: str | None


class AccountOut(Out):
    id: UUID
    space_id: UUID
    type: str
    name: str
    initial_balance_cents: int
    institution: str | None
    balance_cents: int
    pockets_cents: int  # guardado em caixinhas
    available_cents: int  # balance_cents - pockets_cents


class AccountDetailOut(AccountOut):
    pass


class PocketOut(Out):
    id: UUID
    account_id: UUID
    name: str
    cdi_bp: int
    balance_cents: int
    pending_yield_cents: int
    month_yield_cents: int


class PocketMovementOut(Out):
    id: UUID
    pocket_id: UUID
    kind: str
    amount_cents: int
    occurred_on: date
    ref_date: date | None
    created_at: datetime


class PanelGoalOut(Out):
    id: UUID
    name: str


class PocketYieldMonthOut(Out):
    month: date
    yield_cents: int


class PocketPanelOut(Out):
    yield_by_month: list[PocketYieldMonthOut]
    goals: list[PanelGoalOut]


class CdiLatestOut(Out):
    on_date: date
    daily_pct: str
    annual_pct: str


class LoanOut(Out):
    id: UUID
    space_id: UUID
    kind: str
    name: str
    installment_cents: int
    installments_total: int
    first_due_on: date
    category_id: UUID | None
    account_id: UUID | None
    notes: str | None
    canceled_at: datetime | None
    paid_count: int
    remaining_count: int
    remaining_cents: int
    next_due_on: date | None
    last_due_on: date
    progress_pct: int


class InstallmentOut(Out):
    number: int
    due_on: date
    amount_cents: int
    state: Literal["open", "paid_history", "paid_real"]
    bill_id: UUID | None


class CardOut(Out):
    id: UUID
    space_id: UUID
    name: str
    closing_day: int
    due_day: int
    limit_cents: int | None
    payment_account_id: UUID | None


class InvoiceOut(Out):
    id: UUID
    card_id: UUID
    closing_on: date
    due_on: date
    total_cents: int
    paid_cents: int
    remaining_cents: int
    status: str


class PanelCategoryOut(Out):
    category_id: UUID | None
    total_cents: int


class PanelPurchaseOut(Out):
    description: str
    merchant: str | None
    amount_cents: int
    occurred_on: date


class PanelInvoiceOut(Out):
    invoice_id: UUID
    closing_on: date
    due_on: date
    total_cents: int


class CardPanelOut(Out):
    invoice: InvoiceOut | None
    limit_cents: int | None
    used_cents: int
    available_cents: int | None
    by_category: list[PanelCategoryOut]
    private_total_cents: int
    top: list[PanelPurchaseOut]
    history: list[PanelInvoiceOut]


class AccountMoveOut(Out):
    occurred_on: date
    type: str
    description: str
    merchant: str | None
    amount_cents: int


class AccountPanelPocketOut(Out):
    id: UUID
    name: str
    balance_cents: int


class AccountPanelOut(Out):
    month: date
    is_default: bool
    income_cents: int
    expense_cents: int
    transfer_net_cents: int
    private_total_cents: int
    by_category: list[PanelCategoryOut]
    recent: list[AccountMoveOut]
    pockets: list[AccountPanelPocketOut]
    goals: list[PanelGoalOut]


class InvoiceDetailOut(InvoiceOut):
    statement: dict[str, Any]


class TransactionOut(Out):
    id: UUID
    space_id: UUID
    type: str
    amount_cents: int
    occurred_on: date
    description: str
    merchant: str | None
    category_id: UUID | None
    account_id: UUID | None
    counter_account_id: UUID | None
    card_id: UUID | None
    invoice_id: UUID | None
    bill_id: UUID | None
    goal_id: UUID | None
    goal_direction: str | None
    installment_group_id: UUID | None
    installment_number: int | None
    installment_total: int | None
    created_by: UUID | None
    origin: str
    attachment_id: UUID | None
    created_at: datetime


class BillOut(Out):
    id: UUID
    space_id: UUID
    kind: str
    description: str
    amount_cents: int
    due_on: date
    category_id: UUID | None
    responsible_user_id: UUID | None
    status: str
    recurrence_rule: dict[str, Any] | None
    recurrence_id: UUID | None
    invoice_id: UUID | None
    loan_id: UUID | None
    installment_number: int | None
    settled_historical_at: datetime | None
    created_at: datetime


class GoalOut(Out):
    id: UUID
    space_id: UUID
    name: str
    target_cents: int
    deadline: date | None
    account_ids: list[UUID]
    pocket_ids: list[UUID]
    created_on: date
    created_at: datetime


class GoalPanelItemOut(Out):
    id: UUID
    name: str
    balance_cents: int


class GoalPanelPocketOut(GoalPanelItemOut):
    counted: bool


class GoalContributionOut(Out):
    occurred_on: date
    direction: str
    amount_cents: int


class GoalPanelOut(Out):
    total_cents: int
    direct_cents: int
    accounts: list[GoalPanelItemOut]
    pockets: list[GoalPanelPocketOut]
    contributions: list[GoalContributionOut]


class GoalProgressOut(GoalOut):
    saved_cents: int
    monthly_needed_cents: int | None
    behind: bool


class BudgetCategoryOut(Out):
    category_id: UUID
    limit_cents: int
    spent_cents: int


class BudgetOut(Out):
    month: date
    limit_cents: int
    spent_cents: int
    categories: list[BudgetCategoryOut]

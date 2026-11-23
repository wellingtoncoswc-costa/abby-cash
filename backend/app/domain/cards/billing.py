from dataclasses import dataclass
from datetime import date

from app.core.dates import add_months, clamp_day
from app.domain.errors import DomainError


@dataclass(frozen=True)
class InvoiceDates:
    closing: date
    due: date


def invoice_dates_for_month(closing_day: int, due_day: int, year: int, month: int) -> InvoiceDates:
    """Fatura que FECHA em (year, month). Vencimento = primeiro `due_day` depois do fechamento."""
    closing = clamp_day(year, month, closing_day)
    due = clamp_day(year, month, due_day)
    if due <= closing:
        nxt = add_months(date(year, month, 1), 1)
        due = clamp_day(nxt.year, nxt.month, due_day)
    return InvoiceDates(closing, due)


def invoice_dates_for_purchase(closing_day: int, due_day: int, purchase_date: date) -> InvoiceDates:
    """`purchase_date` = dia LOCAL do usuário. <= fechamento: esta fatura; senão, a seguinte."""
    this = invoice_dates_for_month(closing_day, due_day, purchase_date.year, purchase_date.month)
    if purchase_date <= this.closing:
        return this
    nxt = add_months(date(purchase_date.year, purchase_date.month, 1), 1)
    return invoice_dates_for_month(closing_day, due_day, nxt.year, nxt.month)


def split_installments(total_cents: int, n: int) -> list[int]:
    """O resto dos centavos vai na 1ª parcela: 1000/3 -> [334, 333, 333]."""
    if n < 1:
        raise DomainError("invalid_installments")
    if total_cents < n:
        raise DomainError("amount_too_small")
    base, rest = divmod(total_cents, n)
    return [base + rest] + [base] * (n - 1)

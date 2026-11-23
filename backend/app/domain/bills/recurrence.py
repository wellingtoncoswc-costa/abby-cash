from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from app.core.dates import add_months, clamp_day
from app.domain.errors import DomainError


@dataclass(frozen=True)
class Recurrence:
    kind: Literal["monthly", "yearly", "every_n_months"]
    day: int
    month: int | None = None  # só yearly
    n: int = 1  # só every_n_months

    def __post_init__(self) -> None:
        yearly_ok = self.kind != "yearly" or (self.month is not None and 1 <= self.month <= 12)
        if not (
            self.kind in ("monthly", "yearly", "every_n_months")
            and 1 <= self.day <= 31 and self.n >= 1 and yearly_ok
        ):  # fmt: skip
            raise DomainError("invalid_recurrence")

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Recurrence":
        return cls(**data)


def monthly(day: int) -> Recurrence:
    return Recurrence("monthly", day)


def yearly(month: int, day: int) -> Recurrence:
    return Recurrence("yearly", day, month=month)


def every_n_months(n: int, day: int) -> Recurrence:
    return Recurrence("every_n_months", day, n=n)


def generate_occurrences(rule: Recurrence, start: date, horizon_months: int = 3) -> list[date]:
    """Datas de `start` até `start + horizon_months`; dia inexistente vira o último do mês."""
    end = add_months(start, horizon_months)
    step = {"monthly": 1, "every_n_months": rule.n, "yearly": 12}[rule.kind]
    first = date(start.year, rule.month or start.month, 1)
    out: list[date] = []
    k = 0
    while True:
        m = add_months(first, k * step)
        d = clamp_day(m.year, m.month, rule.day)
        k += 1
        if d > end:
            return out
        if d >= start:
            out.append(d)

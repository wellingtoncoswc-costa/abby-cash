import calendar
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def to_local_date(moment: datetime, tz: str) -> date:
    """Dia civil de um instante no fuso do usuário (23:30 em São Paulo ainda é o mesmo dia)."""
    return moment.astimezone(ZoneInfo(tz)).date()


def local_today(tz: str) -> date:
    return to_local_date(datetime.now(UTC), tz)


def clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return clamp_day(y, m + 1, d.day)

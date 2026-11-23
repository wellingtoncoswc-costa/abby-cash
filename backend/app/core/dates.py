import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo


def local_today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return clamp_day(y, m + 1, d.day)

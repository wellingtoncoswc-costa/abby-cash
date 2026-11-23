from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.dates import add_months, clamp_day, local_today


def test_clamp_day():
    assert clamp_day(2026, 2, 31) == date(2026, 2, 28)
    assert clamp_day(2028, 2, 31) == date(2028, 2, 29)
    assert clamp_day(2026, 4, 31) == date(2026, 4, 30)
    assert clamp_day(2026, 3, 15) == date(2026, 3, 15)


def test_add_months():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)


def test_local_today_uses_timezone(monkeypatch):
    # 23:30 em São Paulo (UTC-3) já é o dia seguinte em UTC
    fixed = datetime(2026, 11, 24, 2, 30, tzinfo=ZoneInfo("UTC"))

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz)

    monkeypatch.setattr("app.core.dates.datetime", FakeDT)
    assert local_today("America/Sao_Paulo") == date(2026, 11, 23)
    assert local_today("UTC") == date(2026, 11, 24)

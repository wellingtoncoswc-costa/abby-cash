from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.assistant.models import ConversationState
from app.channels import registry
from app.domain.bills.models import Bill, BillReminderSent
from app.domain.bills.recurrence import monthly
from app.domain.bills.service import create_bill
from app.jobs.bills import daily_bills_job, send_bill_reminders
from tests.assistant.fakes import FakeAdapter
from tests.factories import make_family, make_link, make_user


@pytest.fixture
def tg(monkeypatch) -> FakeAdapter:
    fake = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "telegram", fake)
    return fake


@pytest.fixture
async def ana(session, tg):
    u = await make_user(session, "ana@x.com")
    await make_link(session, u, "111")
    return u


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)  # BRT = UTC-3


async def bill(session, u, due: date, **kw) -> Bill:
    return await create_bill(
        session, actor_id=u.id, space_id=u.default_space_id, description="Luz",
        amount_cents=15_000, due_on=due, **kw,
    )  # fmt: skip


async def test_reminder_sent_once_day_before_and_due_day(session, ana, tg):
    await bill(session, ana, date(2026, 11, 26))
    for _ in range(3):  # 25/11 10:00 BRT, três ciclos
        await send_bill_reminders({}, now=at(25, 13))
    assert [t for _, t in tg.sent] == ["🔔 Amanhã vence: Luz · R$ 150,00."]
    await send_bill_reminders({}, now=at(26, 12, 15))
    await send_bill_reminders({}, now=at(26, 12, 30))
    assert [t for _, t in tg.sent][1] == "🔔 Hoje vence: Luz · R$ 150,00."
    assert len(tg.sent) == 2
    st = await session.scalar(select(ConversationState).where(ConversationState.kind == "reminder"))
    assert st is not None and st.data["last_reminded_bill_ids"]


async def test_reminder_respects_user_timezone(session, ana, tg):
    ana.tz = "Asia/Tokyo"  # UTC+9: 09:00 local = 00:00 UTC
    await session.commit()
    await bill(session, ana, date(2026, 11, 26))
    await send_bill_reminders({}, now=at(24, 23, 30))  # 08:30 em Tóquio, ainda não
    assert tg.sent == []
    await send_bill_reminders({}, now=at(25, 0, 15))  # 09:15 em Tóquio, véspera do vencimento
    assert len(tg.sent) == 1


async def test_overdue_notice_next_day(session, ana, tg):
    await bill(session, ana, date(2026, 11, 24))
    await send_bill_reminders({}, now=at(25, 13))
    assert tg.sent[0][1].startswith("⚠️ Venceu ontem: Luz")
    await send_bill_reminders({}, now=at(26, 13))  # D+2: sem novo aviso
    assert len(tg.sent) == 1


async def test_paid_skipped_and_all_members_when_no_responsible(session, tg):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    await make_link(session, a, "1")
    await make_link(session, b, "2")
    fam = await make_family(session, a, b)
    paid = await create_bill(session, actor_id=a.id, space_id=fam.id, description="Paga",
                             amount_cents=100, due_on=date(2026, 11, 26))  # fmt: skip
    paid.status = "paid"
    await create_bill(session, actor_id=a.id, space_id=fam.id, description="Net",
                      amount_cents=100, due_on=date(2026, 11, 26))  # fmt: skip
    await create_bill(session, actor_id=a.id, space_id=fam.id, description="Só do A",
                      amount_cents=100, due_on=date(2026, 11, 26),
                      responsible_user_id=a.id)  # fmt: skip
    await session.commit()
    await send_bill_reminders({}, now=at(25, 13))
    got = sorted((e, t.split(": ")[1][:6]) for e, t in tg.sent)
    assert got == [("1", "Net · "), ("1", "Só do "), ("2", "Net · ")]


async def test_one_failing_user_does_not_block_others(session, tg, monkeypatch):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    await make_link(session, a, "1")
    await make_link(session, b, "2")
    for u in (a, b):
        await bill(session, u, date(2026, 11, 26))
    real = tg.send_text

    async def flaky(ext, text):
        if ext == "1":
            raise RuntimeError("boom")
        await real(ext, text)

    monkeypatch.setattr(tg, "send_text", flaky)
    await send_bill_reminders({}, now=at(25, 13))
    assert [e for e, _ in tg.sent] == ["2"]
    assert (
        await session.scalar(select(func.count()).select_from(BillReminderSent)) == 1
    )  # falha libera


async def test_recurrence_generated_once_within_3_months(session, ana):
    await bill(session, ana, date(2026, 11, 10), recurrence=monthly(10))
    for _ in range(2):
        await daily_bills_job({}, today=date(2026, 11, 25))
    dues = sorted(await session.scalars(select(Bill.due_on)))
    assert dues == [date(2026, 11, 10), date(2026, 12, 10), date(2027, 1, 10),
                    date(2027, 2, 10)]  # fmt: skip

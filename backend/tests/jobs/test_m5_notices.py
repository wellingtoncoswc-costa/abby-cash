from datetime import UTC, date, datetime

import pytest

from app.core.dates import local_today
from app.domain.bills.service import create_bill
from app.domain.budgets.service import set_budget
from app.domain.goals.service import create_goal
from app.domain.transactions.service import create_transaction
from app.jobs import budgets as jb
from app.jobs import digest as jd
from app.jobs import goals as jg
from tests.factories import category_id, make_account, make_family, make_user

SUN = datetime(2026, 11, 22, 23, 0, tzinfo=UTC)  # domingo 20:00 em São Paulo


@pytest.fixture
def sent(monkeypatch):
    out: list[tuple] = []

    async def fake(uid, text, **kw):
        out.append((uid, text))
        return "telegram"

    for m in (jb, jg, jd):
        monkeypatch.setattr(m, "notify_user", fake)
    return out


async def _spend(session, user, space, amount, on, cat=None):
    acc = await make_account(session, space)
    await create_transaction(
        session, actor_id=user.id, space_id=space, type="expense", amount_cents=amount,
        occurred_on=on, account_id=acc.id, category_id=cat,
    )  # fmt: skip


async def test_budget_alert_message_format(session, sent):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    month = local_today("America/Sao_Paulo").replace(day=1)
    await set_budget(session, actor_id=a.id, space_id=fam.id, month=month, limit_cents=300000)
    await _spend(session, a, fam.id, 240000, month)
    await jb.check_budget_thresholds()
    assert {u for u, _ in sent} == {a.id, b.id}  # todos os membros
    assert all(
        t.startswith("⚠️ Você atingiu 80% do teto de ") and t.endswith("R$ 2.400,00 de R$ 3.000,00.")
        for _, t in sent
    )
    sent.clear()
    await jb.check_budget_thresholds()
    assert sent == []  # um aviso por limiar
    await _spend(session, a, fam.id, 70000, month)
    await jb.check_budget_thresholds()
    assert sent and "ultrapassou o teto" in sent[0][1]


async def test_goal_behind_monthly_notice(session, sent):
    a = await make_user(session, "a@x.com")
    today = date(2026, 11, 1)
    await create_goal(
        session, actor_id=a.id, space_id=a.default_space_id, name="Viagem",
        target_cents=120000, created_on=date(2026, 5, 1), deadline=date(2027, 5, 1),
    )  # fmt: skip
    await jg.notify_goals_behind(today=date(2026, 11, 2))
    assert sent == []  # só no dia 1
    await jg.notify_goals_behind(today=today)
    await jg.notify_goals_behind(today=today)  # idempotente
    assert len(sent) == 1
    assert "Viagem" in sent[0][1] and "R$ 0,00 de R$ 1.200,00" in sent[0][1]
    assert "guarde R$ 200,00 por mês" in sent[0][1]


async def test_weekly_digest_content(session, sent):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    fam = await make_family(session, a, b)
    a.weekly_digest = True
    await session.commit()
    mercado = await category_id(session, fam.id, "Mercado")
    await set_budget(
        session, actor_id=a.id, space_id=fam.id, month=date(2026, 11, 1), limit_cents=100000
    )
    await _spend(session, a, fam.id, 25000, date(2026, 11, 20), mercado)
    await _spend(session, a, fam.id, 5000, date(2026, 11, 21))
    await _spend(session, a, fam.id, 9900, date(2026, 11, 1))  # fora da semana
    await _spend(session, b, b.default_space_id, 77700, date(2026, 11, 20))  # espaço do outro
    await create_bill(
        session, actor_id=a.id, space_id=fam.id, description="Luz", amount_cents=18000,
        due_on=date(2026, 11, 25),
    )  # fmt: skip
    await jd.send_weekly_digests(now=SUN)
    assert [u for u, _ in sent] == [a.id]  # b não ativou
    text = sent[0][1]
    assert "R$ 300,00" in text and "Mercado: R$ 250,00" in text
    assert "R$ 777,00" not in text
    assert "Teto de novembro: 39% usado" in text  # (250+50+99)/1000
    assert "Luz R$ 180,00 — 25/11" in text
    await jd.send_weekly_digests(now=SUN)
    assert len(sent) == 1  # uma por semana


async def test_digest_only_sunday_8pm_local(session, sent):
    a = await make_user(session, "a@x.com")
    a.weekly_digest = True
    await session.commit()
    await jd.send_weekly_digests(now=datetime(2026, 11, 22, 22, 0, tzinfo=UTC))  # 19h
    await jd.send_weekly_digests(now=datetime(2026, 11, 23, 23, 0, tzinfo=UTC))  # segunda
    assert sent == []

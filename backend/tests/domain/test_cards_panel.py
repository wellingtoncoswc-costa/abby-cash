from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.cards.panel import card_panel
from app.domain.cards.service import invoice_total, register_card_purchase, register_invoice_total
from tests.factories import category_id, make_card, make_user


async def test_invoice_total_lands_on_the_requested_invoice(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, closing_day=10, due_day=20)
    inv = await register_invoice_total(
        session, actor_id=a.id, card_id=card.id, year=2026, month=8, total_cents=123_456
    )
    assert (inv.closing_on, inv.due_on) == (date(2026, 8, 10), date(2026, 8, 20))
    assert await invoice_total(session, inv.id) == 123_456
    again = await register_invoice_total(  # soma ao que já existe na mesma fatura
        session, actor_id=a.id, card_id=card.id, year=2026, month=8, total_cents=1_000
    )
    assert again.id == inv.id and await invoice_total(session, inv.id) == 124_456


async def test_invoice_total_short_month_closing(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, closing_day=31, due_day=10)
    inv = await register_invoice_total(
        session, actor_id=a.id, card_id=card.id, year=2026, month=2, total_cents=5_000
    )
    assert inv.closing_on == date(2026, 2, 28)  # fecha no último dia do mês curto


async def test_panel_limit_categories_history_and_top(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    card = await make_card(session, a, sp, closing_day=10, due_day=20, limit_cents=100_000)
    mercado = await category_id(session, sp, "Mercado")
    lazer = await category_id(session, sp, "Lazer")
    for amount, cat, on in (
        (30_000, mercado, date(2026, 11, 5)),
        (20_000, lazer, date(2026, 11, 6)),
        (10_000, mercado, date(2026, 11, 7)),
    ):
        await register_card_purchase(
            session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=amount,
            occurred_on=on, category_id=cat, description=f"c{amount}",
        )  # fmt: skip
    for m in range(1, 8):  # 7 faturas antigas para testar o corte em 6
        await register_invoice_total(
            session, actor_id=a.id, card_id=card.id, year=2026, month=m, total_cents=1_000 * m
        )
    p = await card_panel(session, a.id, card.id, today=date(2026, 11, 8))
    assert p["invoice"]["closing_on"] == date(2026, 11, 10)  # a que ainda vai fechar
    assert p["used_cents"] == 60_000 + sum(1_000 * m for m in range(1, 8))
    assert p["available_cents"] == 100_000 - p["used_cents"]
    assert {c["category_id"]: c["total_cents"] for c in p["by_category"]} == {
        mercado: 40_000,
        lazer: 20_000,
    }
    assert [t["amount_cents"] for t in p["top"]] == [30_000, 20_000, 10_000]
    assert len(p["history"]) == 6 and p["history"][-1]["closing_on"] == date(2026, 11, 10)
    assert [h["closing_on"] for h in p["history"]] == sorted(h["closing_on"] for h in p["history"])


async def test_panel_picks_invoice_and_guards_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    card = await make_card(session, a, a.default_space_id)
    other = await make_card(session, a, a.default_space_id, name="Outro")
    inv = await register_invoice_total(
        session, actor_id=a.id, card_id=card.id, year=2026, month=3, total_cents=7_000
    )
    foreign = await register_invoice_total(
        session, actor_id=a.id, card_id=other.id, year=2026, month=3, total_cents=1_000
    )
    p = await card_panel(session, a.id, card.id, today=date(2026, 11, 8), invoice_id=inv.id)
    assert p["invoice"]["id"] == inv.id and p["limit_cents"] is None
    assert p["available_cents"] is None
    for who, cid, iid in ((a, card.id, foreign.id), (b, card.id, None)):
        with pytest.raises(HTTPException) as e:  # fatura de outro cartão / não é membro
            await card_panel(session, who.id, cid, today=date(2026, 11, 8), invoice_id=iid)
        assert e.value.status_code in (403, 404)


async def test_panel_without_invoices(session):
    a = await make_user(session, "a@x.com")
    card = await make_card(session, a, a.default_space_id, limit_cents=50_000)
    p = await card_panel(session, a.id, card.id, today=date(2026, 11, 8))
    assert p["invoice"] is None and p["used_cents"] == 0 and p["available_cents"] == 50_000
    assert p["by_category"] == [] and p["top"] == [] and p["history"] == []

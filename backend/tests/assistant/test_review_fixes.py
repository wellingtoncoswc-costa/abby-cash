from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.assistant.replies import NOT_UNDERSTOOD
from app.assistant.state import set_state
from app.assistant.turn import Draft
from app.domain.bills.service import create_bill
from app.domain.transactions.models import Transaction
from tests.assistant.fakes import expense, intent
from tests.factories import TS, make_account, make_family


async def all_txs(session) -> list[Transaction]:
    q = select(Transaction).execution_options(populate_existing=True)
    return list(await session.scalars(q))


async def test_text_amount_beats_the_model_and_warns(ana, parser, session):
    parser.add(expense(45_000, "Mercado", merchant="Mercado"))
    reply = await ana.say("gastei 45 no mercado")
    assert reply.startswith("⚠️ Usei R$ 45,00, o valor que você digitou.\n✅ R$ 45,00")
    [tx] = await all_txs(session)
    assert tx.amount_cents == 4_500


async def test_model_amount_found_in_the_text_is_kept(ana, parser, session):
    parser.add(expense(2_300, "Transporte", merchant="Uber"))
    reply = await ana.say("uber 2 pessoas 23")
    assert reply.startswith("✅ R$ 23,00")
    assert [t.amount_cents for t in await all_txs(session)] == [2_300]


@pytest.mark.parametrize(
    "kind", ["corrigir", "apagar", "pagar_conta", "nova_conta_a_pagar", "aporte_meta"]
)
async def test_low_confidence_writes_are_not_executed(ana, parser, session, kind):
    parser.add(
        intent(
            kind,
            amount_cents=1_000,
            confidence=0.4,
            description="Luz",
            goal_hint="x",
            occurred_on=date(2026, 12, 1),
        )
    )
    assert await ana.say("sei lá 10") == NOT_UNDERSTOOD
    assert await all_txs(session) == []


async def test_low_confidence_launch_asks_first(ana, parser, session):
    parser.add(expense(1_000, confidence=0.4))
    assert "Posso lançar?" in await ana.say("sei lá 10")
    assert await all_txs(session) == []


async def test_one_open_bill_that_is_not_mentioned_is_confirmed_first(ana, parser, session):
    await create_bill(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id,
        description="Aluguel", amount_cents=300_000, due_on=date(2026, 11, 30),
    )  # fmt: skip
    parser.add(intent("pagar_conta", description="luz"))
    assert await ana.say("paguei a luz") == "Pagar Aluguel R$ 3.000,00? Responda sim ou não"
    assert await all_txs(session) == []
    assert await ana.say("não") == "Ok, não lancei."
    assert await all_txs(session) == []
    parser.add(intent("pagar_conta", description="aluguel"))
    assert (await ana.say("paguei o aluguel")).startswith("✅ Paguei R$ 3.000,00 · Aluguel")


async def test_pay_with_a_vanished_bill_replies_instead_of_asserting(ana, session):
    d = Draft(action="pay", p=intent("pagar_conta"), space_id=ana.user.default_space_id,
              bill_id=uuid4(), confirmed=True)  # fmt: skip
    await set_state(
        session, ana.user.id, "telegram", "confirm", {"draft": d.model_dump(mode="json")}, TS
    )
    assert await ana.say("sim") == "Não encontrei essa conta."


async def test_alert_failure_never_turns_a_saved_expense_into_a_failure(
    ana, parser, session, monkeypatch
):
    from app.assistant.flows import launch

    async def boom(*a, **k):
        raise RuntimeError("alerts down")

    monkeypatch.setattr(launch, "evaluate_thresholds", boom)
    parser.add(expense(4_500, "Mercado", merchant="Mercado"))
    reply = await ana.say("gastei 45 no mercado")
    assert reply.startswith("✅ R$ 45,00 · Mercado")
    assert len(await all_txs(session)) == 1


async def test_weekday_hint_never_overrides_the_model_date(ana, parser, session):
    parser.add(expense(1_000, "Mercado", occurred_on=date(2026, 11, 10)))
    await ana.say("gastei 10 na sexta")
    parser.add(expense(1_000, "Mercado"))
    await ana.say("gastei 10 na sexta")
    first, second = sorted(await all_txs(session), key=lambda t: t.created_at)
    assert (first.occurred_on, second.occurred_on) == (date(2026, 11, 10), date(2026, 11, 20))


async def test_impossible_date_asks_instead_of_clamping(ana, parser, session):
    assert (await ana.say("gastei 10 em 31/02")).startswith("Essa data não existe")
    assert await all_txs(session) == [] and parser.calls == []


async def test_familia_picks_the_oldest_family_space(ana, new_chat, parser, session):
    bia = await new_chat("bia@x.com", "222")
    first = await make_family(
        session, ana.user
    )  # v1: um espaço familiar por dono; ana está em dois
    await make_account(session, first.id, name="Casa")
    second = await make_family(session, bia.user, ana.user)
    await make_account(session, second.id, name="Outra")
    parser.add(expense(1_000, "Mercado"))
    await ana.say("#familia mercado 10")
    assert parser.calls[0][1].space_id == first.id


@pytest.mark.parametrize(
    ("text", "model_cents", "total"),
    [
        ("iphone 15 por 5000 em 12x", 500_000, 500_000),
        ("comprei 2 pneus 800 em 4x", 80_000, 80_000),
    ],
)
async def test_installment_total_from_the_text_is_kept(
    ana, parser, session, text, model_cents, total
):
    from app.domain.cards.models import Invoice
    from tests.factories import make_card

    await make_card(session, ana.user, ana.user.default_space_id, name="Visa")
    parser.add(intent("lancar_parcelado", "Compras", amount_cents=model_cents, card_hint="visa"))
    reply = await ana.say(text)
    assert "Usei" not in reply
    rows = await all_txs(session)
    assert sum(t.amount_cents for t in rows) == total
    assert len(rows) == int(text.split(" em ")[1].rstrip("x"))
    assert len(list(await session.scalars(select(Invoice)))) == len(rows)

from datetime import date

import pytest

from app.assistant import links
from app.assistant.flows.analysis import pct_change
from app.core.config import get_settings
from app.domain.bills.service import create_bill
from app.domain.transactions.service import create_transaction
from tests.assistant.fakes import intent
from tests.assistant.test_queries import TODAY, spend
from tests.factories import category_id, make_account


def test_links_use_public_base_without_trailing_slash(monkeypatch):
    monkeypatch.setattr(get_settings(), "PUBLIC_BASE_URL", "https://app.example.com/")
    assert links.caixinhas() == "https://app.example.com/caixinhas"
    assert links.financiamentos() == "https://app.example.com/financiamentos"
    assert links.lancamentos() == "https://app.example.com/lancamentos"
    assert links.analises("mes", TODAY, TODAY) == "https://app.example.com/analises"
    assert (
        links.analises("mes_passado", TODAY, TODAY)
        == "https://app.example.com/analises?per=anterior"
    )
    assert links.analises("semana", date(2026, 11, 19), TODAY, expenses=True) == (
        "https://app.example.com/analises?per=custom&start=2026-11-19&end=2026-11-25&type=expense"
    )


@pytest.mark.parametrize(
    ("cur", "prev", "out"),
    [(150, 100, "+50%"), (50, 100, "-50%"), (100, 100, "0%"), (1, 0, "—"), (0, 0, "—"),
     (101, 300, "-66%"), (1005, 1000, "+1%"), (1004, 1000, "0%")],
)  # fmt: skip
def test_pct_change(cur, prev, out):
    assert pct_change(cur, prev) == out


async def seed(session, ana):
    sp = ana.user.default_space_id
    acc = await make_account(session, sp, name="Nubank")
    await spend(session, ana.user, sp, acc, 20_000, "Mercado")
    await spend(session, ana.user, sp, acc, 10_000, "Lazer", on=date(2026, 11, 3))
    await spend(session, ana.user, sp, acc, 5_000, "Mercado", on=date(2026, 11, 2))
    await spend(
        session, ana.user, sp, acc, 10_000, "Lazer", on=date(2026, 10, 20)
    )  # janela anterior de mesmo tamanho
    await create_transaction(
        session, actor_id=ana.user.id, space_id=sp, type="income", amount_cents=100_000,
        occurred_on=TODAY, account_id=acc.id,
        category_id=await category_id(session, sp, "Salário", "income"),
    )  # fmt: skip
    return sp, acc


async def test_resumo_shortcut_uses_overview_and_links_to_analyses(ana, session, parser):
    sp, acc = await seed(session, ana)
    await create_bill(
        session,
        actor_id=ana.user.id,
        space_id=sp,
        description="Luz",
        amount_cents=15_000,
        due_on=date(2026, 11, 28),
    )
    await create_bill(
        session,
        actor_id=ana.user.id,
        space_id=sp,
        description="Net",
        amount_cents=9_000,
        due_on=date(2026, 12, 20),
    )
    reply = await ana.say("resumo do mês")
    assert parser.calls == []  # atalho sem IA
    assert reply == (
        "📊 Resumo em novembro\n"
        "Receitas R$ 1.000,00 · Despesas R$ 350,00 · Saldo R$ 650,00\n"
        "Despesas vs período anterior: +250%\n"
        "Maiores categorias: Mercado R$ 250,00 (71%) · Lazer R$ 100,00 (28%)\n"
        "Contas nos próximos 7 dias: 1 (R$ 150,00)"
        f"\nDetalhes no painel:\n{links.analises('mes', TODAY, TODAY)}"
    )


async def test_resumo_period_prev_zero_and_merchant(ana, session, parser):
    sp, acc = await seed(session, ana)
    await create_transaction(
        session, actor_id=ana.user.id, space_id=sp, type="expense", amount_cents=7_000,
        occurred_on=TODAY, account_id=acc.id, merchant="Padaria Sol",
        category_id=await category_id(session, sp, "Mercado"),
    )  # fmt: skip
    parser.add(intent("resumo_periodo", period="hoje"))
    reply = await ana.say("resumão de hoje")
    assert "Resumo hoje" in reply and "Despesas R$ 270,00" in reply
    assert "Despesas vs período anterior: —" in reply  # ontem sem despesas
    assert "Maior estabelecimento: Padaria Sol R$ 70,00" in reply
    assert "Nenhuma conta vence nos próximos 7 dias." in reply
    assert reply.endswith(links.analises("hoje", TODAY, TODAY))
    assert "per=custom&start=2026-11-25&end=2026-11-25" in reply
    assert len(reply.splitlines()) <= 12


async def test_resumo_previous_month_period_link(ana, session, parser):
    await seed(session, ana)
    parser.add(intent("resumo_periodo", period="mes_passado"))
    reply = await ana.say("comparar com o mês passado")
    assert "Resumo em outubro" in reply and "Despesas R$ 100,00" in reply
    assert reply.endswith("/analises?per=anterior")


async def test_maiores_gastos_top5_with_category(ana, session, parser):
    sp, acc = await seed(session, ana)
    for i, v in enumerate((900, 800, 700), 1):
        await spend(session, ana.user, sp, acc, v, "Lazer", on=date(2026, 11, i))
    parser.add(intent("maiores_gastos", period="mes"))
    reply = await ana.say("no que mais gastei")
    lines = reply.splitlines()
    assert lines[0] == "💸 Maiores gastos em novembro:"
    assert lines[1].startswith("• 25/11 · ") and "R$ 200,00 · Mercado" in lines[1]
    assert len([x for x in lines if x.startswith("•")]) == 5
    assert "R$ 100,00 · Lazer" in lines[2]
    assert reply.endswith(links.analises("mes", TODAY, TODAY, expenses=True))
    assert await ana.say("maiores gastos") == reply  # atalho
    assert len(parser.calls) == 1


async def test_empty_space_is_friendly(ana, parser):
    for text in ("resumo", "maiores gastos"):
        reply = await ana.say(text)
        assert reply.startswith("Sem lançamentos em novembro.") and "gastei 45" in reply
        assert "analises" not in reply


async def test_only_active_space_and_no_spouse_personal(session, new_chat, parser):
    from tests.factories import make_family

    husband, wife = await new_chat("h@x.com", "111"), await new_chat("w@x.com", "222")
    fam = await make_family(session, husband.user, wife.user)
    wife_acc = await make_account(session, wife.user.default_space_id, name="Segredo da Bia")
    await spend(session, wife.user, wife.user.default_space_id, wife_acc, 77_700, "Lazer")
    reply = await husband.say("resumo")
    assert reply.startswith("Sem lançamentos") and "777" not in reply
    assert fam is not None
    assert (await husband.say("maiores gastos")).startswith("Sem lançamentos")


async def test_help_and_prompt_mention_analysis(ana):
    from app.ai.openai_parser import INSTRUCTIONS

    assert "resumo do mês" in await ana.say("ajuda")
    assert "resumo_periodo" in INSTRUCTIONS and "maiores_gastos" in INSTRUCTIONS

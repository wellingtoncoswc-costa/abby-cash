from datetime import date

from sqlalchemy import update

from app.domain.budgets.service import set_budget
from app.domain.cards.service import register_card_purchase
from app.domain.transactions.service import create_transaction
from app.domain.users.models import User
from tests.assistant.fakes import expense, intent
from tests.factories import category_id, make_account, make_card, make_family

TODAY = date(2026, 11, 25)


async def spend(session, user, space, acc, amount, category, on=TODAY):
    return await create_transaction(
        session, actor_id=user.id, space_id=space, type="expense", amount_cents=amount,
        occurred_on=on, category_id=await category_id(session, space, category),
        account_id=acc.id,
    )  # fmt: skip


async def test_shortcuts_do_not_call_the_llm(ana, parser):
    assert (await ana.say("ajuda")).startswith("Eu lanço seus gastos pelo chat.")
    assert (await ana.say("saldo")).startswith("💰 Saldos:\n• Carteira: R$ 0,00")
    assert parser.calls == []


async def test_gastos_by_period_and_category(ana, parser, session):
    sp = ana.user.default_space_id
    acc = await make_account(session, sp, name="Nubank")
    await spend(session, ana.user, sp, acc, 5_000, "Mercado")
    await spend(session, ana.user, sp, acc, 3_000, "Mercado", on=date(2026, 11, 24))
    await spend(session, ana.user, sp, acc, 2_000, "Lazer", on=date(2026, 11, 2))
    await spend(session, ana.user, sp, acc, 9_900, "Lazer", on=date(2026, 10, 30))
    assert await ana.say("gastos") == (  # atalho: sem IA
        "📊 Gastos em novembro: R$ 100,00 — Pessoal\n• Mercado: R$ 80,00\n• Lazer: R$ 20,00"
    )
    assert parser.calls == []
    parser.add(intent("consultar_gastos", "Mercado", period="hoje"))
    assert await ana.say("quanto gastei de mercado hoje") == "📊 Gastos hoje: R$ 50,00 — Pessoal"
    parser.add(intent("consultar_gastos", period="mes_passado"))
    assert (await ana.say("e mês passado?")).startswith("📊 Gastos em outubro: R$ 99,00")
    parser.add(intent("consultar_gastos", period="ontem"))
    assert (await ana.say("e ontem?")).startswith("📊 Gastos ontem: R$ 30,00")
    parser.add(intent("consultar_gastos", "Pets", period="hoje"))
    assert await ana.say("gastos com pets hoje") == "Nenhum gasto hoje — Pessoal."
    parser.add(intent("consultar_gastos", period="hoje").model_copy(update={"category_index": 999}))
    assert await ana.say("gastos com x") == "Não achei essa categoria."


async def test_gastos_sum_card_purchases_by_purchase_date_not_due_month(ana, session):
    sp = ana.user.default_space_id
    card = await make_card(session, ana.user, sp, name="Visa", closing_day=10, due_day=20)
    await register_card_purchase(
        session, actor_id=ana.user.id, space_id=sp, card_id=card.id, amount_cents=7_000,
        occurred_on=TODAY, category_id=await category_id(session, sp, "Lazer"),
    )  # fmt: skip  # fatura vence em dezembro, mas a compra é de hoje
    assert (await ana.say("gastos")).startswith("📊 Gastos em novembro: R$ 70,00")


async def test_gastos_never_include_spouse_personal_expenses(session, new_chat, parser):
    husband, wife = await new_chat("h@x.com", "111"), await new_chat("w@x.com", "222")
    fam = await make_family(session, husband.user, wife.user)
    fam_acc = await make_account(session, fam.id, name="Casa")
    wife_acc = await make_account(session, wife.user.default_space_id, name="Segredo da Bia")
    await spend(session, wife.user, fam.id, fam_acc, 10_000, "Mercado")
    await spend(session, wife.user, wife.user.default_space_id, wife_acc, 77_700, "Lazer")
    await session.execute(
        update(User).where(User.id == husband.user.id).values(default_space_id=fam.id)
    )
    await session.commit()
    reply = await husband.say("gastos")
    assert reply == "📊 Gastos em novembro: R$ 100,00 — Casa\n• Mercado: R$ 100,00"
    assert "777" not in reply and "Lazer" not in reply
    own = await husband.say("#pessoal gastos")  # o #pessoal do marido é o dele
    assert own == "Nenhum gasto em novembro — Pessoal."


async def test_saldo_only_own_spaces(session, new_chat):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    await make_account(session, ana.user.default_space_id, name="Nubank", initial=12_345)
    await make_account(session, bia.user.default_space_id, name="Segredo da Bia", initial=999_999)
    reply = await ana.say("saldo")
    assert "Nubank: R$ 123,45" in reply and "Carteira: R$ 0,00" in reply
    assert "Segredo" not in reply and "9.999,99" not in reply
    assert reply.endswith("Total: R$ 123,45")
    assert "Segredo da Bia: R$ 9.999,99" in await bia.say("saldo")


async def test_faturas_show_only_the_private_aggregate_never_the_details(session, new_chat, parser):
    husband, wife = await new_chat("h@x.com", "111"), await new_chat("w@x.com", "222")
    fam = await make_family(session, husband.user, wife.user)
    card = await make_card(session, husband.user, fam.id, name="Visa", closing_day=10, due_day=20)
    await register_card_purchase(
        session, actor_id=husband.user.id, space_id=fam.id, card_id=card.id, amount_cents=10_000,
        occurred_on=TODAY, description="Mercado da casa",
    )  # fmt: skip
    parser.add(expense(30_000, "Compras", card_hint="visa", merchant="Presente surpresa"))
    reply = await wife.say("#pessoal presente surpresa 300 no visa")
    assert "Cartão Visa" in reply and "🔒 pessoal" in reply
    seen = await husband.say("faturas")
    assert seen == (
        "💳 Visa · vence 20/12: R$ 400,00 em aberto · Outros lançamentos (privados): R$ 300,00"
    )
    assert "Presente" not in seen
    assert await wife.say("fatura") == "💳 Visa · vence 20/12: R$ 400,00 em aberto"  # ela vê tudo


async def test_faturas_none_and_outsider_sees_nothing(session, new_chat):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    card = await make_card(session, ana.user, ana.user.default_space_id, name="Visa")
    await register_card_purchase(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, card_id=card.id,
        amount_cents=5_000, occurred_on=TODAY,
    )  # fmt: skip
    assert await bia.say("faturas") == "Nenhuma fatura em aberto."
    assert "R$ 50,00 em aberto" in await ana.say("faturas")


async def test_teto_overview_and_missing_budget(ana, parser, session):
    sp = ana.user.default_space_id
    assert await ana.say("teto") == (
        "Você ainda não definiu um teto para novembro. Defina no painel web."
    )
    mercado = await category_id(session, sp, "Mercado")
    await set_budget(
        session, actor_id=ana.user.id, space_id=sp, month=date(2026, 11, 1),
        limit_cents=300_000, categories={mercado: 100_000},
    )  # fmt: skip
    parser.add(expense(40_000, "Mercado"))
    await ana.say("gastei 400 no mercado")
    assert await ana.say("teto") == (
        "🎯 Teto de novembro: R$ 400,00 de R$ 3.000,00 (13%).\n• Mercado: R$ 400,00 de R$ 1.000,00"
    )

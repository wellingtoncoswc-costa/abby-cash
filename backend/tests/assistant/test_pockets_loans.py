from datetime import date

from sqlalchemy import func, select

from app.assistant import links
from app.domain.loans.service import create_loan
from app.domain.pockets.models import PocketMovement
from app.domain.pockets.service import create_pocket, deposit
from tests.assistant.fakes import intent
from tests.assistant.test_idempotency import crash_and_retry
from tests.factories import make_account, make_family


async def pocket(session, user, name="Reserva", acc=None, cdi_bp=12_000, space_id=None):
    sp = space_id or user.default_space_id
    acc = acc or await make_account(session, sp, name="Nubank", initial=500_000)
    return await create_pocket(
        session, actor_id=user.id, space_id=sp, account_id=acc.id, name=name, cdi_bp=cdi_bp
    )


async def moves(session) -> int:
    return await session.scalar(select(func.count()).select_from(PocketMovement))


async def test_guardar_executes_at_once_and_resgatar_reverses(ana, session, parser):
    await pocket(session, ana.user)
    parser.add(intent("guardar_caixinha", amount_cents=20_000, pocket_hint="reserva"))
    assert await ana.say("guardei 200 na reserva") == (
        "✅ R$ 200,00 guardados em Reserva · saldo R$ 200,00"
    )
    parser.add(intent("resgatar_caixinha", amount_cents=5_000, pocket_hint="Reserva"))
    assert await ana.say("tirei 50 da reserva") == (
        "✅ R$ 50,00 resgatados de Reserva · saldo R$ 150,00"
    )


async def test_single_pocket_without_name_is_used(ana, session, parser):
    await pocket(session, ana.user)
    parser.add(intent("guardar_caixinha", amount_cents=10_000))
    assert (await ana.say("guardei 100")).startswith("✅ R$ 100,00 guardados em Reserva")


async def test_no_pocket_points_to_panel(ana, parser):
    parser.add(intent("guardar_caixinha", amount_cents=10_000, pocket_hint="reserva"))
    assert await ana.say("guardei 100 na reserva") == (
        "Você ainda não tem caixinhas. Crie uma no painel web (Caixinhas)."
    )


async def test_ambiguous_or_missing_name_asks_by_number(ana, session, parser):
    acc = await make_account(session, ana.user.default_space_id, name="Inter", initial=500_000)
    await pocket(session, ana.user, "Viagem Europa", acc)
    await pocket(session, ana.user, "Viagem Praia", acc)
    parser.add(intent("guardar_caixinha", amount_cents=10_000, pocket_hint="viagem"))
    assert await ana.say("guardei 100 na viagem") == (
        "Em qual caixinha? Responda com o número:\n1) Viagem Europa\n2) Viagem Praia"
    )
    assert (await ana.say("2")).startswith("✅ R$ 100,00 guardados em Viagem Praia")
    assert await moves(session) == 1
    assert (await ana.say("2")).startswith("Não entendi")  # estado consumido: sem 2º depósito
    assert await moves(session) == 1
    parser.add(intent("resgatar_caixinha", amount_cents=1_000))  # sem nome, duas caixinhas
    assert (await ana.say("tirei 10")).startswith("De qual caixinha? Responda com o número:")
    assert (await ana.say("Europa")).startswith("A caixinha Viagem Europa tem só R$ 0,00;")


async def test_missing_amount_asks_then_runs(ana, session, parser):
    await pocket(session, ana.user)
    parser.add(intent("guardar_caixinha", pocket_hint="reserva"))
    assert await ana.say("guardei na reserva") == "Quanto você guardou? (ex.: 200)"
    assert (await ana.say("200")).startswith("✅ R$ 200,00 guardados em Reserva")


async def test_insufficient_available_and_balance_explain_with_values(ana, session, parser):
    acc = await make_account(session, ana.user.default_space_id, name="Nubank", initial=30_000)
    p = await pocket(session, ana.user, acc=acc)
    parser.add(intent("guardar_caixinha", amount_cents=50_000, pocket_hint="reserva"))
    assert await ana.say("guardei 500 na reserva") == (
        "A conta Nubank tem só R$ 300,00 disponíveis (fora das caixinhas); você pediu R$ 500,00."
    )
    await deposit(session, actor_id=ana.user.id, pocket_id=p.id, amount_cents=10_000)
    parser.add(intent("resgatar_caixinha", amount_cents=15_000, pocket_hint="reserva"))
    assert await ana.say("tirei 150 da reserva") == (
        "A caixinha Reserva tem só R$ 100,00; você pediu R$ 150,00."
    )
    parser.add(intent("guardar_caixinha", amount_cents=25_000, pocket_hint="reserva"))
    assert (await ana.say("guardei 250 na reserva")).startswith("A conta Nubank tem só R$ 200,00")
    assert await moves(session) == 1


async def test_repeated_message_does_not_deposit_twice(ana, session, parser):
    await pocket(session, ana.user)
    parser.add(intent("guardar_caixinha", amount_cents=20_000, pocket_hint="reserva"))
    assert await crash_and_retry(session, ana, "guardei 200 na reserva") == "Já registrei isso."
    assert await moves(session) == 1


async def test_space_isolation(ana, new_chat, session, parser):
    bia = await new_chat("bia@x.com", "222")
    await pocket(session, bia.user, "Segredo")
    parser.add(intent("guardar_caixinha", amount_cents=10_000, pocket_hint="segredo"))
    assert (await ana.say("guardei 100 no segredo")).startswith("Você ainda não tem caixinhas")
    parser.add(intent("consultar_caixinhas"))
    assert (await ana.say("minhas caixinhas")).startswith("Você ainda não tem caixinhas")
    assert await moves(session) == 0
    fam = await make_family(session, ana.user)  # #familia: só as caixinhas do espaço familiar
    await pocket(session, ana.user, "Casa", space_id=fam.id)
    parser.add(intent("guardar_caixinha", amount_cents=10_000, pocket_hint="casa"))
    assert (await ana.say("#pessoal guardei 100 na casa")).startswith("Você ainda não tem")
    parser.add(intent("guardar_caixinha", amount_cents=10_000, pocket_hint="casa"))
    assert (await ana.say("#familia guardei 100 na casa")).startswith("✅ R$ 100,00 guardados")


async def test_query_pockets_lists_balance_cdi_month_yield_total_and_available(
    ana, session, parser
):
    p = await pocket(session, ana.user, "Reserva", cdi_bp=11_050)
    await deposit(session, actor_id=ana.user.id, pocket_id=p.id, amount_cents=20_000)
    assert await ana.say("minhas caixinhas") == (  # atalho: o parser nem é chamado
        "🎯 Caixinhas:\n"
        "• Reserva: R$ 200,00 · 110,5% do CDI · rendeu R$ 0,00 no mês\n"
        "Total: R$ 200,00\n"
        "Disponível na conta Nubank: R$ 4.800,00\n"
        f"Detalhes no painel:\n{links.caixinhas()}"
    )
    assert parser.calls == []


async def loan(session, user, name="Carro", kind="financing", total=12):
    return await create_loan(
        session, actor_id=user.id, space_id=user.default_space_id, kind=kind, name=name,
        installment_cents=100_000, installments_total=total, first_due_on=date(2026, 12, 10),
    )  # fmt: skip


async def test_query_loans_list_and_detail(ana, session, parser):
    assert (await ana.say("financiamentos")).startswith("Você ainda não tem financiamentos")
    await loan(session, ana.user)
    await loan(session, ana.user, "Casa", "consortium", 60)
    assert await ana.say("meus financiamentos") == (
        "🎯 Financiamentos:\n"
        "• Carro (financiamento): 0 de 12 pagas · faltam R$ 12.000,00 · próxima R$ 1.000,00 "
        "em 10/12\n"
        "• Casa (consórcio): 0 de 60 pagas · faltam R$ 60.000,00 · próxima R$ 1.000,00 em 10/12\n"
        f"Detalhes no painel:\n{links.financiamentos()}"
    )
    parser.add(intent("consultar_financiamentos", pocket_hint="carro"))
    assert await ana.say("quanto falta do carro") == (
        "🎯 Financiamentos:\n"
        "• Carro (financiamento): 0 de 12 pagas · faltam R$ 12.000,00 · próxima R$ 1.000,00 "
        "em 10/12 · termina em 11/2027\n"
        f"Detalhes no painel:\n{links.financiamentos()}"
    )
    parser.add(intent("consultar_financiamentos", pocket_hint="moto"))
    assert (await ana.say("quanto falta da moto")).startswith("Não achei esse financiamento.")


async def test_paguei_financiamento_pays_the_open_installment(ana, session, parser):
    from app.domain.bills.models import Bill

    await loan(session, ana.user)
    parser.add(intent("pagar_conta", description="financiamento do carro"))
    reply = await ana.say("paguei o financiamento do carro")
    assert reply.startswith("✅ Paguei R$ 1.000,00 · Carro (1/12)")
    paid = await session.scalar(select(Bill.status).where(Bill.installment_number == 1))
    assert paid == "paid"


async def test_create_goes_to_the_panel_and_help_lists_commands(ana, parser):
    for text in ("quero criar uma caixinha", "cadastrar financiamento do carro"):
        reply = await ana.say(text)
        assert reply.startswith("Caixinhas e financiamentos são criados no painel")
        assert links.caixinhas() in reply and links.financiamentos() in reply
    help_ = await ana.say("ajuda")
    for needle in ("caixinhas", "guardei 200 na reserva", "tirei 100 da viagem",
                   "paguei o financiamento do carro", "financiamentos"):  # fmt: skip
        assert needle in help_
    assert parser.calls == []


async def test_low_confidence_pocket_write_is_not_executed(ana, session, parser):
    await pocket(session, ana.user)
    parser.add(intent("guardar_caixinha", amount_cents=10_000, confidence=0.3))
    assert (await ana.say("sei lá 100 reserva")).startswith("Não entendi")
    assert await moves(session) == 0


async def test_paguei_financiamento_skips_historical_installments(ana, session, parser):
    from app.domain.bills.models import Bill

    await create_loan(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, kind="financing",
        name="Carro", installment_cents=100_000, installments_total=12,
        first_due_on=date(2026, 12, 10), paid_installments=2,
    )  # fmt: skip
    parser.add(intent("pagar_conta", description="financiamento do carro"))
    reply = await ana.say("paguei o financiamento do carro")
    assert reply.startswith("✅ Paguei R$ 1.000,00 · Carro (3/12)")
    st = await session.scalars(select(Bill.status).where(Bill.installment_number == 3))
    assert list(st) == ["paid"]

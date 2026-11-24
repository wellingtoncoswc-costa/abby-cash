from datetime import date, timedelta

from sqlalchemy import func, select

from app.assistant.flows.create import parse_cdi_bp, parse_due
from app.domain.bills.models import Bill
from app.domain.loans.models import Loan
from app.domain.pockets.models import Pocket
from tests.assistant.fakes import intent
from tests.assistant.test_idempotency import crash_and_retry
from tests.factories import TS, make_account, make_family


async def pockets(session) -> list[Pocket]:
    return list(await session.scalars(select(Pocket)))


async def loans(session) -> list[Loan]:
    return list(await session.scalars(select(Loan)))


def test_parse_cdi_bp_is_integer_and_bounded():
    assert parse_cdi_bp("115") == 11_500
    assert parse_cdi_bp("102,5%") == 10_250
    assert parse_cdi_bp("120% do CDI") == 12_000
    assert parse_cdi_bp("0,01") == 1
    assert parse_cdi_bp("1000") == 100_000
    for bad in ("0", "0,001", "1000,01", "1001", "abc", "", "-5", "1e3"):
        assert parse_cdi_bp(bad) is None


def test_parse_due_accepts_day_month_year_and_day_only():
    today = date(2026, 11, 25)
    assert parse_due("10/12/2026", today) == date(2026, 12, 10)
    assert parse_due("10/12", today) == date(2026, 12, 10)
    assert parse_due("10/01", today) == date(2027, 1, 10)
    assert parse_due("dia 10", today) == date(2026, 12, 10)
    assert parse_due("30", today) == date(2026, 11, 30)
    assert parse_due("dia 31", date(2026, 11, 25)) == date(2026, 12, 31)
    assert parse_due("05/03/2024", today) == date(2024, 3, 5)  # passado vale (já pagas)
    for bad in ("31/02/2026", "31/02", "32", "0", "10/13", "ontem", "abc"):
        assert parse_due(bad, today) is None


async def test_create_pocket_all_fields_in_message_then_confirm(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Itaú")
    await make_account(session, ana.user.default_space_id, name="Nubank")
    parser.add(
        intent(
            "criar_caixinha",
            new_name="Reserva de emergência",
            cdi_bp=12_000,
            account_hint="nubank",
        )
    )
    assert await ana.say("criar caixinha reserva de emergência a 120% do CDI na conta nubank") == (
        "Criar caixinha Reserva de emergência na conta Nubank, rendendo 120% do CDI? "
        "Responda com o número:\n1) Sim\n2) Não"
    )
    assert await pockets(session) == []
    assert await ana.say("1") == (
        "✅ Caixinha Reserva de emergência criada na conta Nubank, rendendo 120% do CDI."
    )
    [p] = await pockets(session)
    assert (p.name, p.cdi_bp, p.space_id) == (
        "Reserva de emergência",
        12_000,
        ana.user.default_space_id,
    )


async def test_create_pocket_asks_one_thing_at_a_time(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Itaú")
    await make_account(session, ana.user.default_space_id, name="Nubank")
    parser.add(intent("criar_caixinha"))
    assert await ana.say("criar caixinha") == "Qual o nome da caixinha?"
    assert await ana.say("Viagem") == (
        "Em qual conta fica a caixinha? Responda com o número:\n"
        "1) Carteira\n2) Conta Itaú\n3) Conta Nubank"
    )
    assert (await ana.say("3")).startswith("Quanto ela rende, em % do CDI?")

    assert await ana.say("4") == "Qual percentual do CDI? (ex.: 102,5)"
    assert (await ana.say("102,5%")).startswith(
        "Criar caixinha Viagem na conta Nubank, rendendo 102,5% do CDI?"
    )
    assert (await ana.say("sim")).startswith("✅ Caixinha Viagem criada")
    [p] = await pockets(session)
    assert (p.cdi_bp, p.name) == (10_250, "Viagem")


async def test_create_pocket_uses_the_only_account_and_a_preset(ana, session, parser):
    parser.add(intent("criar_caixinha", new_name="Reserva"))  # só a Carteira padrão
    assert (await ana.say("nova caixinha reserva")).startswith("Quanto ela rende")
    assert (await ana.say("115")).startswith("Criar caixinha Reserva em Carteira, rendendo 115%")
    assert (await ana.say("1")).startswith("✅")
    assert [p.cdi_bp for p in await pockets(session)] == [11_500]


async def test_confirmation_no_cancels_and_cancel_word_too(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Nubank")
    parser.add(intent("criar_caixinha", new_name="Reserva", cdi_bp=10_000, account_hint="nubank"))
    await ana.say("criar caixinha reserva a 100%")
    assert await ana.say("não") == "Ok, não criei."
    parser.add(intent("criar_caixinha", new_name="Reserva", cdi_bp=10_000, account_hint="nubank"))
    await ana.say("criar caixinha reserva a 100%")
    assert await ana.say("cancelar") == "Ok, cancelei."
    assert await pockets(session) == []


async def test_unexpected_answer_repeats_once_then_cancels(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Nubank")
    parser.add(intent("criar_caixinha", new_name="Reserva", account_hint="nubank"))
    await ana.say("criar caixinha reserva")
    assert (await ana.say("blablabla")).startswith("Não entendi. Quanto ela rende")
    assert await ana.say("1001") == "Ok, cancelei. Mande de novo quando quiser."
    assert await pockets(session) == []
    assert (await ana.say("1")).startswith("Não entendi")  # nada pendente


async def test_confirmation_consumed_atomically_no_double_create(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Nubank")
    parser.add(intent("criar_caixinha", new_name="Reserva", cdi_bp=10_000, account_hint="nubank"))
    await ana.say("criar caixinha reserva a 100%")
    await crash_and_retry(session, ana, "1", msg_id=50)  # reentrega: estado já consumido
    assert len(await pockets(session)) == 1


async def test_expired_question_does_not_create(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Nubank")
    parser.add(intent("criar_caixinha", new_name="Reserva", cdi_bp=10_000, account_hint="nubank"))
    await ana.say("criar caixinha reserva a 100%")
    assert (await ana.say("1", ts=TS + timedelta(minutes=31))).startswith("Não entendi")
    assert await pockets(session) == []


async def test_without_ai_the_guided_flow_still_starts(ana, session, parser):
    assert await ana.say("quero criar uma caixinha") == "Qual o nome da caixinha?"
    await ana.say("cancelar")
    assert (await ana.say("cadastrar financiamento do carro")).startswith("Qual o nome do financ")


async def test_pocket_only_in_accounts_of_the_target_space(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Nubank")
    fam = await make_family(session, ana.user)
    parser.add(intent("criar_caixinha", new_name="Casa", cdi_bp=10_000))
    assert (await ana.say("#familia criar caixinha casa a 100%")).startswith(
        "Não achei nenhuma conta"
    )  # a família ainda não tem conta
    await make_account(session, fam.id, name="Conjunta")
    parser.add(intent("criar_caixinha", new_name="Casa", cdi_bp=10_000, account_hint="nubank"))
    out = await ana.say("#familia criar caixinha casa a 100% no nubank")
    assert out.startswith("Criar caixinha Casa na conta Conjunta")  # nubank é de outro espaço
    await ana.say("1")
    [p] = await pockets(session)
    assert p.space_id == fam.id


async def test_create_loan_with_everything_in_the_message(ana, session, parser):
    parser.add(
        intent(
            "criar_financiamento",
            new_name="Carro",
            amount_cents=189_000,
            loan_installments=48,
            first_due_on=date(2026, 12, 10),
            paid_installments=17,
        )
    )
    assert await ana.say(
        "novo financiamento do carro, 48 parcelas de 1.890 começando 10/12, já paguei 17"
    ) == (
        "Criar financiamento Carro: 48 parcelas de R$ 1.890,00, 1º vencimento 10/12/2026, "
        "17 já pagas? Responda com o número:\n1) Sim\n2) Não"
    )
    assert await loans(session) == []
    out = await ana.say("1")
    assert out.startswith(
        "✅ Financiamento Carro criado: 48 parcelas de R$ 1.890,00 · 17 já baixadas"
    )
    [ln] = await loans(session)
    assert (ln.kind, ln.installments_total, ln.installment_cents) == ("financing", 48, 189_000)
    hist = await session.scalar(
        select(func.count())
        .select_from(Bill)
        .where(
            Bill.loan_id == ln.id, Bill.status == "paid", Bill.settled_historical_at.is_not(None)
        )
    )
    assert hist == 17


async def test_create_consortium_guided(ana, session, parser):
    parser.add(intent("criar_financiamento", new_name="Imóvel"))
    assert (await ana.say("cadastrar consórcio do imóvel")).startswith("Qual o valor da parcela?")
    assert await ana.say("2.500") == "Quantas parcelas no total? (1 a 480)"
    assert (await ana.say("100")).startswith("Qual a data do 1º vencimento?")
    assert (await ana.say("dia 10")).startswith(
        "Quantas parcelas você já pagou antes de cadastrar?"
    )
    assert (await ana.say("nenhuma")).startswith(
        "Criar consórcio Imóvel: 100 parcelas de R$ 2.500,00, 1º vencimento 10/12/2026?"
    )
    assert (await ana.say("sim")).startswith("✅ Consórcio Imóvel criado")
    [ln] = await loans(session)
    assert (ln.kind, ln.first_due_on) == ("consortium", date(2026, 12, 10))


async def test_loan_kind_asked_when_text_does_not_say(ana, session, parser):
    parser.add(intent("criar_financiamento", new_name="Moto"))
    assert (await ana.say("cadastrar a moto parcelada")).startswith("É financiamento ou consórcio?")
    assert (await ana.say("2")).startswith("Qual o valor da parcela?")


async def test_loan_validations_repeat_then_cancel(ana, session, parser):
    parser.add(
        intent(
            "criar_financiamento",
            new_name="Carro",
            amount_cents=100_000,
            loan_installments=12,
            first_due_on=date(2026, 12, 10),
        )
    )
    assert (await ana.say("novo financiamento carro")).startswith("Quantas parcelas você já pagou")
    assert (await ana.say("13")).startswith("Não entendi. Quantas parcelas você já pagou")
    assert await ana.say("-1") == "Ok, cancelei. Mande de novo quando quiser."
    parser.add(intent("criar_financiamento", new_name="Carro", loan_installments=12))
    await ana.say("novo financiamento carro")
    assert (await ana.say("1.000")).startswith("Qual a data do 1º")
    assert (await ana.say("31/02/2026")).startswith("Não entendi. Qual a data")
    assert (await ana.say("dia 32")).startswith("Ok, cancelei")
    parser.add(intent("criar_financiamento", new_name="Carro"))
    await ana.say("novo financiamento carro")
    await ana.say("1.000")
    assert (await ana.say("481")).startswith("Não entendi. Quantas parcelas no total")
    assert await loans(session) == []


async def test_loan_confirmation_consumed_once(ana, session, parser):
    parser.add(
        intent(
            "criar_financiamento",
            new_name="Carro",
            amount_cents=100_000,
            loan_installments=12,
            first_due_on=date(2026, 12, 10),
            paid_installments=0,
        )
    )
    await ana.say("novo financiamento carro")
    await crash_and_retry(session, ana, "1", msg_id=50)
    assert len(await loans(session)) == 1
    assert (await ana.say("1")).startswith("Não entendi")
    assert len(await loans(session)) == 1


async def test_no_confusion_with_saving_into_pocket_and_queries(ana, session, parser):
    from tests.assistant.test_pockets_loans import pocket

    await pocket(session, ana.user)
    parser.add(intent("guardar_caixinha", amount_cents=20_000, pocket_hint="reserva"))
    assert (await ana.say("guardei 200 na reserva")).startswith("✅ R$ 200,00 guardados em Reserva")
    assert (await ana.say("meus financiamentos")).startswith("Você ainda não tem financiamentos")
    assert len(await pockets(session)) == 1 and await loans(session) == []

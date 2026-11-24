from sqlalchemy import func, select

from app.assistant.flows.installments import refine
from app.assistant.intents import ParsedIntent
from app.domain.bills.models import Bill
from app.domain.transactions.models import Transaction
from tests.assistant.fakes import intent
from tests.assistant.test_idempotency import crash_and_retry
from tests.assistant.test_pockets_loans import loan
from tests.factories import make_account


async def bill(session, number: int, loan_name: str = "Carro") -> Bill | None:
    return await session.scalar(
        select(Bill).where(
            Bill.installment_number == number, Bill.description.like(f"{loan_name}%")
        )
    )


async def txs(session) -> int:
    return await session.scalar(select(func.count()).select_from(Transaction))


MODE = (
    "Parcela 3/12 do Carro (R$ 1.000,00, vence 10/02/2027). Responda com o número:\n"
    "1) Já estava paga antes (só baixa, sem lançamento)\n"
    "2) Paguei agora (escolher conta e lançar)"
)


async def test_single_installment_history_has_no_transaction(ana, session, parser):
    await loan(session, ana.user)
    parser.add(intent("baixar_parcela", installment_number=3, pocket_hint="carro"))
    assert await ana.say("paguei a parcela 3 do financiamento do carro") == MODE
    reply = await ana.say("1")
    assert reply == "✅ Parcela 3/12 do Carro baixada (sem lançamento). Pagas: 1 de 12."
    b = await bill(session, 3)
    assert (b.status, b.settled_historical_at is not None) == ("paid", True)
    assert await txs(session) == 0
    parser.add(intent("baixar_parcela", installment_number=3, pocket_hint="carro"))
    assert (await ana.say("paguei a parcela 3 do carro")).endswith(
        "já estava baixada (paga antes, sem lançamento)."
    )


async def test_single_installment_paid_now_materializes_and_posts(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Nubank", initial=500_000)
    await make_account(session, ana.user.default_space_id, name="Itaú", initial=500_000)
    await loan(session, ana.user)
    assert await bill(session, 7) is None  # ainda não gerada
    parser.add(intent("baixar_parcela", installment_number=7, pocket_hint="carro"))
    await ana.say("paguei a parcela 7 do carro")
    assert (await ana.say("2")).startswith(
        "De qual conta saiu? Responda com o número:\n1) Carteira\n2) Conta Itaú\n3) Conta Nubank"
    )
    reply = await crash_and_retry(session, ana, "3", msg_id=60)
    assert reply == "Já registrei isso."
    assert await txs(session) == 1
    b = await bill(session, 7)
    assert b.status == "paid" and b.settled_historical_at is None
    tx = await session.scalar(select(Transaction))
    assert (tx.amount_cents, tx.origin, tx.source_message_id) == (100_000, "telegram", "111:60")
    parser.add(intent("baixar_parcela", installment_number=7, pocket_hint="carro"))
    assert "pagamento real não se desfaz" in await ana.say("paguei a parcela 7 do carro")


async def test_account_hint_skips_the_question(ana, session, parser):
    await make_account(session, ana.user.default_space_id, name="Nubank", initial=500_000)
    await make_account(session, ana.user.default_space_id, name="Itaú", initial=500_000)
    await loan(session, ana.user)
    parser.add(
        intent("baixar_parcela", installment_number=2, pocket_hint="carro", account_hint="itaú")
    )
    await ana.say("paguei a parcela 2 do carro pelo itaú")
    reply = await ana.say("2")
    assert reply.startswith("✅ Paguei R$ 1.000,00 · Carro (2/12) · hoje · Conta Itaú")


async def test_through_n_batch_history_with_confirmation(ana, session, parser):
    await loan(session, ana.user)
    parser.add(intent("baixar_parcela", installment_number=2, pocket_hint="carro"))
    await ana.say("paguei a parcela 2 do carro")
    await ana.say("1")
    parser.add(intent("baixar_parcela", installment_number=5, through=True, pocket_hint="carro"))
    assert await ana.say("já paguei até a 5 do carro") == (
        "Dar baixa (sem lançamento) em 4 parcelas do Carro, da 1 até a 5 (1 já estavam pagas)? "
        "Responda com o número:\n1) Sim\n2) Não"
    )
    assert await bill(session, 5) is None
    assert await ana.say("1") == (
        "✅ 4 parcelas do Carro baixadas, da 1 até a 5, sem lançamento. Pagas: 5 de 12."
    )
    for n in range(1, 6):
        assert (await bill(session, n)).settled_historical_at is not None
    assert await txs(session) == 0
    parser.add(intent("baixar_parcela", installment_number=5, through=True, pocket_hint="carro"))
    assert await ana.say("já paguei até a 5 do carro") == (
        "Todas as parcelas até a 5 do Carro já estão pagas."
    )


async def test_batch_not_confirmed_does_nothing(ana, session, parser):
    await loan(session, ana.user)
    parser.add(intent("baixar_parcela", installment_number=4, through=True, pocket_hint="carro"))
    await ana.say("já paguei até a 4 do carro")
    assert await ana.say("2") == "Ok, não dei baixa."
    assert await bill(session, 1) is None or (await bill(session, 1)).status == "open"


async def test_asks_loan_when_ambiguous_and_number_when_missing(ana, session, parser):
    await loan(session, ana.user)
    await loan(session, ana.user, "Casa", "consortium", 60)
    parser.add(intent("baixar_parcela", installment_number=1))
    assert await ana.say("paguei a parcela 1") == (
        "Qual financiamento? Responda com o número:\n1) Carro\n2) Casa"
    )
    assert (await ana.say("2")).startswith("Parcela 1/60 do Casa")
    await ana.say("cancelar")
    parser.add(intent("baixar_parcela", pocket_hint="casa"))
    assert await ana.say("paguei uma parcela da casa") == "Qual parcela do Casa? (1 a 60)"
    assert (await ana.say("61")).startswith("Esse número não existe. Qual parcela")
    assert (await ana.say("12")).startswith("Parcela 12/60 do Casa")


async def test_paguei_financiamento_without_number_keeps_old_route(ana, session, parser):
    await loan(session, ana.user)
    parser.add(intent("pagar_conta", description="financiamento do carro"))
    assert (await ana.say("paguei o financiamento do carro")).startswith(
        "✅ Paguei R$ 1.000,00 · Carro (1/12)"
    )
    # o modelo errou para pagar_conta, mas há nº de parcela: vai para a baixa de parcela
    parser.add(intent("pagar_conta", description="parcela 5 do financiamento do carro"))
    assert (await ana.say("paguei a parcela 5 do financiamento do carro")).startswith(
        "Parcela 5/12 do Carro"
    )


def test_refine_distinguishes_the_two_phrases():
    pay = ParsedIntent.of("pagar_conta")
    assert refine("paguei o financiamento do carro", pay).intent == "pagar_conta"
    assert refine("paguei", pay).intent == "pagar_conta"
    assert refine("paguei 1500 de aluguel dia 10", pay).intent == "pagar_conta"
    got = refine("paguei a parcela 12 do financiamento do carro", pay)
    assert (got.intent, got.installment_number, got.through) == ("baixar_parcela", 12, None)
    got = refine("já paguei até a 17 do consórcio", pay)
    assert (got.intent, got.installment_number, got.through) == ("baixar_parcela", 17, True)
    assert refine("paguei até dia 10", pay).intent == "pagar_conta"
    keep = ParsedIntent.of("baixar_parcela", installment_number=3)
    assert refine("paguei a parcela 12", keep).installment_number == 3
    assert refine("guardei 200 na reserva", ParsedIntent.of("guardar_caixinha")).intent == (
        "guardar_caixinha"
    )


async def test_isolation_and_partial_installment(ana, new_chat, session, parser):
    bia = await new_chat("bia@x.com", "222")
    await loan(session, bia.user)
    parser.add(intent("baixar_parcela", installment_number=1, pocket_hint="carro"))
    assert (await ana.say("paguei a parcela 1 do carro")).startswith(
        "Você ainda não tem financiamentos"
    )
    paid = select(func.count()).select_from(Bill).where(Bill.status == "paid")
    assert await session.scalar(paid) == 0

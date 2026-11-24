from datetime import date

from sqlalchemy import select

from app.assistant import links
from app.domain.pockets.service import create_pocket, deposit
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import account_balance
from tests.assistant.fakes import intent
from tests.assistant.test_idempotency import crash_and_retry
from tests.factories import make_account, make_family


async def setup_accounts(session, ana):
    sp = ana.user.default_space_id
    nu = await make_account(session, sp, name="Nubank", initial=100_000)
    it = await make_account(session, sp, name="Itaú", initial=10_000)
    return nu, it


async def txs(session):
    return list(await session.scalars(select(Transaction).where(Transaction.type == "transfer")))


def transfer(**f):
    return intent("transferir_contas", **f)


async def test_transfer_executes_at_once_and_updates_balances(ana, session, parser):
    nu, it = await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=30_000, account_hint="nubank", to_account_hint="itau"))
    assert await ana.say("transferi 300 do Nubank para o Itaú") == (
        f"✅ R$ 300,00 · Nubank → Itaú · hoje\nDetalhes no painel:\n{links.lancamentos()}"
    )
    assert await account_balance(session, nu.id) == 70_000
    assert await account_balance(session, it.id) == 40_000
    [tx] = await txs(session)
    assert (tx.origin, tx.created_by) == ("telegram", ana.user.id)


async def test_typed_amount_wins_over_model(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=999, account_hint="nubank", to_account_hint="itau"))
    assert (await ana.say("passa 200 da conta nubank pra itau")).startswith("✅ R$ 200,00")


async def test_missing_origin_then_destination_asked_one_at_a_time(ana, session, parser):
    nu, it = await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=50_000))
    q = await ana.say("move 500")
    assert q.startswith("De qual conta saiu? Responda com o número:\n1) ")
    q = await ana.say("Nubank")  # nome também vale
    assert q.startswith("Para qual conta foi? Responda com o número:")
    assert "Nubank" not in q and "Itaú" in q  # a origem sai da lista
    assert await txs(session) == []
    assert await ana.say("9") == "Responda com um dos números da lista."
    assert "Nubank → Itaú · hoje\nDetalhes no painel:" in await ana.say("Itaú")
    assert await account_balance(session, it.id) == 60_000


async def test_missing_destination_lists_other_accounts(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=50_000, account_hint="itau"))
    q = await ana.say("mandei 500 do itaú")
    assert "Itaú" not in q.split("\n", 1)[1] and q.startswith("Para qual conta foi?")
    assert (await ana.say("1")).startswith("✅ R$ 500,00 · Itaú → ")
    assert (await ana.say("1")).startswith("Não entendi")  # estado consumido: sem 2ª transferência
    assert len(await txs(session)) == 1


async def test_same_account_is_explained(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=10_000, account_hint="nubank", to_account_hint="nubank"))
    assert await ana.say("passa 100 do nubank pro nubank") == (
        "Conta Nubank é a origem e o destino. Diga duas contas diferentes."
    )
    assert await txs(session) == []


async def test_missing_amount_asks_and_zero_is_refused(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(account_hint="nubank", to_account_hint="itau"))
    assert await ana.say("transferi do nubank pro itau") == "Quanto você transferiu? (ex.: 300)"
    assert (await ana.say("300")).startswith("✅ R$ 300,00 · Nubank → Itaú")


async def test_low_confidence_does_not_execute(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=1_000, account_hint="nubank", to_account_hint="itau",
                        confidence=0.4))  # fmt: skip
    assert (await ana.say("sei lá 10")).startswith("Não entendi")
    assert await txs(session) == []


async def test_only_one_account_explains(ana, session, parser):
    parser.add(transfer(amount_cents=1_000, account_hint="carteira", to_account_hint="x"))
    assert (await ana.say("transferi 10")).startswith("Para transferir preciso de pelo menos duas")


async def test_type_words_pick_savings_and_checking(ana, session, parser):
    sp = ana.user.default_space_id
    pou = await make_account(session, sp, name="Nubank Cofre", type="savings", initial=90_000)
    cor = await make_account(session, sp, name="Itaú", initial=0)
    parser.add(transfer(amount_cents=100_000, account_hint="poupança", to_account_hint="corrente"))
    assert await ana.say("mandei 1000 da poupança pra corrente") == (
        "✅ R$ 1.000,00 · Nubank Cofre → Itaú · hoje\nDetalhes no painel:\n" + links.lancamentos()
    )
    assert await account_balance(session, cor.id) == 100_000 and pou


async def test_insufficient_available_with_pockets_explains(ana, session, parser):
    nu, it = await setup_accounts(session, ana)
    p = await create_pocket(
        session, actor_id=ana.user.id, space_id=ana.user.default_space_id, account_id=nu.id,
        name="Reserva", cdi_bp=12_000,
    )  # fmt: skip
    await deposit(session, actor_id=ana.user.id, pocket_id=p.id, amount_cents=80_000)
    parser.add(transfer(amount_cents=30_000, account_hint="nubank", to_account_hint="itau"))
    assert await ana.say("transferi 300 do nubank pro itau") == (
        "A conta Nubank tem só R$ 200,00 disponíveis (fora das caixinhas); você pediu R$ 300,00."
    )
    assert await txs(session) == []


async def test_yesterday_date_and_future_refused(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=1_000, account_hint="nubank", to_account_hint="itau"))
    await ana.say("transferi 10 do nubank pro itau ontem")
    assert [t.occurred_on for t in await txs(session)] == [date(2026, 11, 24)]
    parser.add(transfer(amount_cents=1_000, account_hint="nubank", to_account_hint="itau",
                        occurred_on=date(2026, 12, 30)))  # fmt: skip
    assert (await ana.say("transferi 10 do nubank pro itau")).startswith("Essa data é no futuro")


async def test_idempotent_by_message(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=1_000, account_hint="nubank", to_account_hint="itau"))
    assert await crash_and_retry(session, ana, "transferi 10 do nubank pro itau") == (
        "Já registrei isso."
    )
    assert len(await txs(session)) == 1


async def test_apagar_deletes_transfer_after_confirmation(ana, session, parser):
    nu, it = await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=30_000, account_hint="nubank", to_account_hint="itau"))
    await ana.say("transferi 300 do nubank pro itau")
    assert await ana.say("apagar último") == "Apagar R$ 300,00 · transferência? Responda sim ou não"
    assert len(await txs(session)) == 1
    assert await ana.say("sim") == "🗑️ Apaguei: R$ 300,00 · Nubank → Itaú · hoje"
    assert await txs(session) == []
    assert await account_balance(session, nu.id) == 100_000


async def test_corrigir_transfer_is_refused(ana, session, parser):
    await setup_accounts(session, ana)
    parser.add(transfer(amount_cents=30_000, account_hint="nubank", to_account_hint="itau"))
    await ana.say("transferi 300 do nubank pro itau")
    parser.add(intent("corrigir", amount_cents=2_000))
    assert await ana.say("corrigir valor 20") == "Esse lançamento não pode ser corrigido pelo chat."


async def test_across_spaces_uses_source_space(ana, session, parser, new_chat):
    bia = await new_chat("bia@x.com", "222")
    fam = await make_family(session, ana.user, bia.user)
    pessoal = await make_account(session, ana.user.default_space_id, name="Pessoal", initial=50_000)
    await make_account(session, fam.id, name="Conjunta")
    parser.add(transfer(amount_cents=10_000, account_hint="pessoal", to_account_hint="conjunta"))
    assert await ana.say("passei 100 da pessoal pra conjunta") == (
        "✅ R$ 100,00 · Pessoal → Conjunta · hoje\nDetalhes no painel:\n" + links.lancamentos()
    )
    [tx] = await txs(session)
    assert tx.space_id == ana.user.default_space_id and tx.account_id == pessoal.id

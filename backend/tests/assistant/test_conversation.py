import asyncio
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select

from app.api import webhooks
from app.assistant.replies import MEDIA, NOT_UNDERSTOOD
from app.domain.accounts.service import set_default_account
from app.domain.budgets.service import set_budget
from app.domain.channels.models import InboundMessage
from app.domain.transactions.models import Transaction
from app.domain.users.models import User
from app.jobs.inbound import process_inbound
from tests.assistant.fakes import expense, intent
from tests.factories import (
    TS,
    category_id,
    make_account,
    make_card,
    make_family,
    make_link,
    make_user,
)

CONFIRM_TAIL = '\nResponda "corrigir" se errei.'


async def txs(session) -> list[Transaction]:
    q = (
        select(Transaction)
        .order_by(Transaction.created_at)
        .execution_options(populate_existing=True)
    )
    return list(await session.scalars(q))


async def nubank_default(session, user) -> None:
    acc = await make_account(session, user.default_space_id, name="Nubank")
    await set_default_account(
        session, actor_id=user.id, space_id=user.default_space_id, account_id=acc.id
    )


async def test_expense_message_creates_tx_and_confirms(ana, parser, session):
    await nubank_default(session, ana.user)
    parser.add(expense(4500, "Alimentação", merchant="Mercado"))
    reply = await ana.say("gastei 45 no mercado")
    assert reply == "✅ R$ 45,00 · Alimentação · Mercado · hoje · Conta Nubank" + CONFIRM_TAIL
    [tx] = await txs(session)
    assert (tx.amount_cents, tx.type, tx.origin, tx.source_message_id) == (
        4500, "expense", "telegram", "111:1",
    )  # fmt: skip
    assert (tx.created_by, tx.space_id) == (ana.user.id, ana.user.default_space_id)
    assert tx.occurred_on == date(2026, 11, 25)
    text, ctx = parser.calls[0]
    assert text == "gastei 45 no mercado" and ctx.today == date(2026, 11, 25)


async def test_date_hint_account_hint_and_income(ana, parser, session):
    await nubank_default(session, ana.user)
    parser.add(expense(6700, "Alimentação", merchant="iFood", account_hint="dinheiro"))
    reply = await ana.say("ifood 67 ontem no dinheiro")
    assert reply.startswith("✅ R$ 67,00 · Alimentação · iFood · ontem · Carteira")
    parser.add(intent("lancar_receita", "Salário", amount_cents=300_000, account_hint="nubank"))
    reply = await ana.say("recebi 3000 de salário no nubank")
    assert reply.startswith("✅ R$ 3.000,00 · Salário · hoje · Conta Nubank")
    first, second = await txs(session)
    assert first.occurred_on == date(2026, 11, 24) and second.type == "income"


async def test_private_tag_goes_to_personal_space(ana, parser, session):
    fam = await make_family(session, ana.user)
    await session.execute(
        User.__table__.update().where(User.id == ana.user.id).values(default_space_id=fam.id)
    )
    await session.commit()
    parser.add(expense(15_000, "Compras", description="presente"))
    reply = await ana.say("#pessoal presente 150")
    [tx] = await txs(session)
    personal = await session.scalar(select(User.default_space_id).where(User.id == ana.user.id))
    assert tx.space_id != fam.id and tx.space_id is not None
    assert "🔒 pessoal" in reply and "Carteira" in reply
    assert parser.calls[0][1].space_id == tx.space_id  # o contexto da IA também é o pessoal
    assert personal == fam.id  # o padrão continua sendo a família


async def test_model_private_flag_cannot_move_the_expense(ana, parser, session):
    fam = await make_family(session, ana.user)
    await session.execute(
        User.__table__.update().where(User.id == ana.user.id).values(default_space_id=fam.id)
    )
    await session.commit()
    parser.add(expense(1000, "Compras", private=True))  # a etiqueta é só do texto
    await ana.say("gastei 10")
    [tx] = await txs(session)
    assert tx.space_id == fam.id


async def test_family_tag_asks_account_then_resumes(ana, parser, session):
    fam = await make_family(session, ana.user)
    await make_account(session, fam.id, name="Casa")
    parser.add(expense(32_000, "Mercado"))
    reply = await ana.say("#familia mercado 320")
    assert reply.startswith("Em qual conta foi? Responda com o número:")
    assert "1) Carteira" in reply and "2) Conta Casa" in reply
    reply = await ana.say("2")
    assert reply.startswith("✅ R$ 320,00 · Mercado · hoje · Conta Casa")
    [tx] = await txs(session)
    assert tx.space_id == fam.id and len(parser.calls) == 1  # a resposta não passou pela IA


async def test_family_tag_without_family_space(ana, parser):
    parser.add(expense(1000))
    assert (await ana.say("#familia pão 10")).startswith("Você não tem um espaço familiar")


async def test_missing_amount_asks_and_resumes(ana, parser, session):
    parser.add(expense(None, "Mercado", merchant="Mercado"))
    reply = await ana.say("fui no mercado")
    assert reply == "Quanto foi? (ex.: 45 ou 45,50)"
    assert await txs(session) == []
    reply = await ana.say("45,50")
    assert reply.startswith("✅ R$ 45,50 · Mercado · Mercado · hoje · Carteira")
    assert len(parser.calls) == 1


async def test_zero_amount_rejected(ana, parser, session):
    parser.add(expense(None, merchant="Mercado"))  # o modelo não aceita 0: devolve nulo
    reply = await ana.say("gastei 0 no mercado")
    assert reply.startswith("O valor precisa ser maior que zero.")
    assert await txs(session) == []
    assert (await ana.say("0")).startswith("O valor precisa ser maior que zero.")
    assert (await ana.say("-10")).startswith("O valor precisa ser maior que zero.")
    assert (await ana.say("12")).startswith("✅ R$ 12,00")  # a pergunta seguia de pé


async def test_zero_amount_never_reaches_the_domain_even_if_the_parser_lets_it_through(
    ana, parser, session
):
    bad = expense(1000).model_copy(update={"amount_cents": 0})  # sem validação: força o 0
    parser.add(bad)
    assert (await ana.say("gastei 10")).startswith("O valor precisa ser maior que zero.")
    assert await txs(session) == []


async def test_answer_that_is_a_new_command_is_not_taken_as_the_amount(ana, parser, session):
    parser.add(expense(None, merchant="Mercado"))
    await ana.say("fui no mercado")
    parser.add(expense(3000, "Transporte", merchant="Uber"))
    reply = await ana.say("gastei 30 de uber")  # outra mensagem, não "30" do mercado
    assert reply.startswith("✅ R$ 30,00 · Transporte · Uber")
    [tx] = await txs(session)
    assert tx.merchant == "Uber"


async def test_state_expires_after_30_minutes(ana, parser, session):
    parser.add(expense(None, merchant="Mercado"))
    await ana.say("fui no mercado")
    reply = await ana.say("45", ts=TS + timedelta(minutes=31))
    assert reply == NOT_UNDERSTOOD and await txs(session) == []


async def test_low_confidence_asks_to_confirm(ana, parser, session):
    parser.add(expense(4500, merchant="Padaria", confidence=0.4))
    reply = await ana.say("acho que foi 45 na padaria")
    assert reply == 'Entendi R$ 45,00 em "Padaria". Posso lançar? (sim/não)'
    assert await txs(session) == []
    assert (await ana.say("sim")).startswith("✅ R$ 45,00")
    parser.add(expense(900, merchant="Bala", confidence=0.2))
    await ana.say("sei lá, uns 9 de bala")
    assert await ana.say("não") == "Ok, não lancei."
    assert len(await txs(session)) == 1


async def test_cancel_clears_pending_question(ana, parser, session):
    parser.add(expense(None))
    await ana.say("gastei no mercado")
    assert await ana.say("cancelar") == "Ok, cancelei."
    assert await ana.say("45") == NOT_UNDERSTOOD


async def test_the_model_cannot_pick_a_foreign_account_card_or_category(session, new_chat, parser):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    await make_account(session, bia.user.default_space_id, name="Segredo da Bia")
    await make_card(session, bia.user, bia.user.default_space_id, name="Visa da Bia")
    parser.add(expense(1000, account_hint="Segredo da Bia"))
    reply = await ana.say("gastei 10 na conta segredo da bia")
    assert reply.startswith("Em qual conta foi?") and "Bia" not in reply  # só as contas dela
    parser.add(expense(1000, category_index=999, card_hint="visa da bia"))
    assert (await ana.say("gastei 10 no visa da bia")).startswith("Não achei nenhum cartão")
    assert await txs(session) == []
    parser.add(expense(1000).model_copy(update={"category_index": 999}))  # fora da lista
    await ana.say("cancelar")
    reply = await ana.say("gastei 10")
    assert "· Outros ·" in reply


async def test_parcelado_reply_mentions_future_budgets(ana, parser, session):
    sp = ana.user.default_space_id
    await make_card(session, ana.user, sp, name="Visa", closing_day=10, due_day=20)
    for month in (date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)):
        await set_budget(
            session, actor_id=ana.user.id, space_id=sp, month=month, limit_cents=1_000_000
        )
    parser.add(
        intent(
            "lancar_parcelado",
            "Compras",
            amount_cents=60_000,
            installments=3,
            card_hint="visa",
            merchant="TV",
        )
    )
    reply = await ana.say("tv 600 em 3x no visa")
    assert "em 3x de R$ 200,00" in reply
    assert "Compromete R$ 200,00 dos tetos de dez, jan e fev." in reply
    assert [t.installment_number for t in await txs(session)] == [1, 2, 3]


async def test_parcelado_reply_format_and_card_choice(ana, parser, session):
    sp = ana.user.default_space_id
    await make_card(session, ana.user, sp, name="Visa")
    parser.add(
        intent(
            "lancar_parcelado",
            "Compras",
            amount_cents=30_000,
            installments=3,
            card_hint="visa",
            merchant="TV",
        )
    )
    reply = await ana.say("tv 300 em 3x no visa")
    assert reply.startswith("✅ R$ 300,00 em 3x de R$ 100,00 · Compras · TV · hoje · Cartão Visa")
    assert len(await txs(session)) == 3


async def test_threshold_alert_is_appended_and_every_member_notified(
    session, new_chat, parser, adapter
):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    fam = await make_family(session, ana.user, bia.user)
    acc = await make_account(session, fam.id, name="Casa")
    await set_default_account(session, actor_id=ana.user.id, space_id=fam.id, account_id=acc.id)
    await set_budget(
        session, actor_id=ana.user.id, space_id=fam.id, month=date(2026, 11, 1), limit_cents=10_000
    )
    parser.add(expense(8_500, "Mercado"))
    reply = await ana.say("#familia mercado 85")
    alert = "⚠️ Você atingiu 80% do teto de novembro: R$ 85,00 de R$ 100,00."
    assert reply.endswith(alert)
    assert ("222", alert) in adapter.sent  # a Bia também é avisada
    assert ("111", alert) not in adapter.sent  # a Ana recebe junto da confirmação, uma vez só
    parser.add(expense(1_500, "Mercado"))
    reply = await ana.say("#familia mercado 15")
    assert "⚠️ Você atingiu 100% do teto" in reply


async def test_alert_goes_through_each_members_preferred_channel(
    session, new_chat, parser, adapter, monkeypatch
):
    from app.channels import registry
    from app.domain.channels.models import ChannelLink
    from tests.assistant.fakes import FakeAdapter

    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    other = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "whatsapp_evolution", other)
    session.add(
        ChannelLink(user_id=bia.user.id, channel="whatsapp_evolution", external_user_id="55")
    )
    await session.execute(
        User.__table__.update()
        .where(User.id == bia.user.id)
        .values(preferred_channel="whatsapp_evolution")
    )
    await session.commit()
    fam = await make_family(session, ana.user, bia.user)
    acc = await make_account(session, fam.id, name="Casa")
    await set_default_account(session, actor_id=ana.user.id, space_id=fam.id, account_id=acc.id)
    await set_budget(
        session, actor_id=ana.user.id, space_id=fam.id, month=date(2026, 11, 1), limit_cents=10_000
    )
    parser.add(expense(8_500, "Mercado"))
    await ana.say("#familia mercado 85")
    assert [e for e, _ in other.sent] == ["55"] and adapter.sent[-1][0] == "111"


async def test_domain_errors_become_polite_replies(ana, parser, session):
    await make_card(session, ana.user, ana.user.default_space_id, name="Visa")
    parser.add(intent("lancar_parcelado", amount_cents=1000, installments=60, card_hint="visa"))
    assert await ana.say("tv 10 em 60 parcelas") == "Parcelas: de 2 a 48."
    assert await txs(session) == []


async def test_parcelado_without_a_card_explains(ana, parser):
    parser.add(intent("lancar_parcelado", amount_cents=60_000, installments=3))
    reply = await ana.say("tv 600 em 3x")
    assert reply.startswith("Não achei nenhum cartão cadastrado.")


async def test_future_date_is_refused(ana, parser, session):
    parser.add(expense(1000, occurred_on=date(2026, 11, 26)))
    assert (await ana.say("gastei 10 amanhã")).startswith("Essa data é no futuro")
    assert await txs(session) == []


async def test_llm_failure_fallback(ana, parser, session):
    parser.add(RuntimeError("openai down"))
    reply = await ana.say("gastei 45 no mercado")
    assert reply.startswith("⚠️ A IA está indisponível agora; lancei do jeito simples")
    assert "✅ R$ 45,00 · Outros · no mercado · hoje · Carteira" in reply
    [tx] = await txs(session)
    assert tx.amount_cents == 4500 and tx.description == "no mercado"
    outros = await category_id(session, ana.user.default_space_id, "Outros")
    assert tx.category_id == outros
    parser.add(RuntimeError("openai down"))
    assert (await ana.say("bom dia")) == NOT_UNDERSTOOD  # sem valor não dá para adivinhar
    parser.add(TimeoutError())
    reply = await ana.say("recebi 3000 de salário")
    assert "✅ R$ 3.000,00 · Outros" in reply and (await txs(session))[-1].type == "income"


async def test_without_a_configured_parser_the_fallback_is_used(ana, session):
    ana.parser = None
    reply = await ana.say("gastei 45 no mercado")
    assert reply.startswith("⚠️ A IA está indisponível")


async def test_media_message_gets_polite_reply(ana, parser, session):
    assert await ana.say("", media_kind="audio") == MEDIA
    assert await ana.say("farmácia 87,40", media_kind="image") == MEDIA  # legenda não grava
    assert await txs(session) == [] and parser.calls == []


async def test_unknown_goes_to_not_understood_and_help_lists_examples(ana, parser):
    parser.add(intent("desconhecido"))
    assert await ana.say("qual a capital da França") == NOT_UNDERSTOOD
    assert "gastei 45 no mercado" in await ana.say("ajuda")
    assert (await ana.say("7")) == NOT_UNDERSTOOD  # número sem pergunta pendente


async def test_duplicate_webhook_creates_single_transaction(
    client, session, adapter, parser, monkeypatch
):
    ana = await make_user(session, "ana@x.com")
    await make_link(session, ana, "111")
    ana_id = ana.id
    ids: list[UUID] = []

    async def record(inbound_id: UUID) -> None:
        ids.append(inbound_id)

    monkeypatch.setattr(webhooks, "enqueue_inbound", record)
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 10, "from": {"id": 111, "is_bot": False},
            "chat": {"id": 111, "type": "private"}, "date": 1795618800,
            "text": "gastei 45 no mercado",
        },
    }  # fmt: skip
    posts = [client.post("/webhooks/telegram", json=payload) for _ in range(6)]
    assert [r.status_code for r in await asyncio.gather(*posts)] == [200] * 6  # simultâneos
    assert (await client.post("/webhooks/telegram", json=payload)).status_code == 200  # e depois
    assert len(set(ids)) == 1  # reenfileiradas, mas é o mesmo id (o ARQ dedupe por _job_id)
    parser.add(expense(4500, "Mercado"))
    # mesmo que a fila entregue o mesmo job várias vezes, só uma execução grava
    await asyncio.gather(*[process_inbound({"parser": parser}, str(i)) for i in ids[:1] * 4])
    assert len(await txs(session)) == 1
    assert len(adapter.sent) == 1 and len(parser.calls) == 1
    session.expire_all()
    row = await session.scalar(select(InboundMessage))
    assert row.status == "processed" and row.user_id == ana_id
    assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 1


async def test_unexpected_error_marks_row_failed_and_apologizes(ana, parser, session, monkeypatch):
    from app.assistant.flows import launch

    async def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(launch, "run", boom)
    parser.add(expense(4500))
    assert (await ana.say("gastei 45")).startswith("Tive um problema ao processar")
    row = await session.scalar(select(InboundMessage))
    assert row.status == "failed"


async def test_one_failing_message_does_not_block_the_next(ana, parser, session, monkeypatch):
    from app.assistant.flows import launch

    real = launch.run

    async def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(launch, "run", boom)
    parser.add(expense(4500))
    await ana.say("gastei 45")
    monkeypatch.setattr(launch, "run", real)
    parser.add(expense(1000))
    assert (await ana.say("gastei 10")).startswith("✅ R$ 10,00")
    rows = list(
        await session.scalars(select(InboundMessage.status).order_by(InboundMessage.created_at))
    )
    assert rows == ["failed", "processed"]


async def test_replies_never_leak_internal_ids(ana, parser, session):
    parser.add(expense(1000))
    reply = await ana.say("gastei 10")
    assert str(ana.user.id) not in reply and "Traceback" not in reply


async def test_correction_learns_rule(ana, parser, session):
    from app.domain.categories.models import CategoryRule

    parser.add(expense(3000, "Alimentação", merchant="Padaria Pão Quente 12"))
    await ana.say("gastei 30 na padaria pão quente 12")
    parser.add(intent("corrigir", "Mercado"))
    reply = await ana.say("era mercado")
    assert reply.startswith("✏️ Corrigi:\n✅ R$ 30,00 · Mercado · Padaria Pão Quente 12")
    mercado = await category_id(session, ana.user.default_space_id, "Mercado")
    rule = await session.scalar(select(CategoryRule))
    assert rule is not None and rule.merchant_norm == "padaria pao quente"
    assert rule.category_id == mercado
    # a regra vence a sugestão do LLM na próxima vez
    parser.add(expense(2000, "Alimentação", merchant="padaria pão quente"))
    reply = await ana.say("20 na padaria pão quente")
    assert "· Mercado ·" in reply
    assert ("padaria pao quente", "Mercado") in parser.calls[-1][1].rules
    # corrigir de novo troca a regra (não duplica)
    parser.add(intent("corrigir", "Lazer"))
    await ana.say("na verdade lazer")
    rules = list(
        await session.scalars(select(CategoryRule).execution_options(populate_existing=True))
    )
    assert len(rules) == 1 and rules[0].category_id != mercado


async def test_correct_shortcut_asks_then_applies_value_and_unknown_category(ana, parser, session):
    from app.assistant.replies import CORRECT_PROMPT

    parser.add(expense(4500, "Mercado", merchant="Mercado"))
    await ana.say("gastei 45 no mercado")
    assert await ana.say("corrigir") == CORRECT_PROMPT
    reply = await ana.say("valor 50")
    assert reply.startswith("✏️ Corrigi:\n✅ R$ 50,00 · Mercado")
    await ana.say("corrigir")
    reply = await ana.say("categoria Inexistente")
    assert reply.startswith("Não achei a categoria Inexistente. Opções:")
    await ana.say("corrigir")
    assert (await ana.say("data ontem")).startswith(
        "✏️ Corrigi:\n✅ R$ 50,00 · Mercado · Mercado · ontem"
    )
    assert [t.amount_cents for t in await txs(session)] == [5000]


async def test_correct_without_a_chat_transaction(ana, parser):
    parser.add(intent("corrigir", amount_cents=100))
    assert (await ana.say("era 1")).startswith("Não achei nenhum lançamento seu feito pelo chat")


async def test_correct_zero_is_refused_and_installments_are_limited(ana, parser, session):
    parser.add(expense(4500, "Mercado"))
    await ana.say("gastei 45 no mercado")
    await ana.say("corrigir")
    assert (await ana.say("valor 0")).startswith("O valor precisa ser maior que zero.")
    await make_card(session, ana.user, ana.user.default_space_id, name="Visa")
    parser.add(intent("lancar_parcelado", amount_cents=30_000, installments=3, card_hint="visa"))
    await ana.say("tv 300 em 3x no visa")
    parser.add(intent("corrigir", amount_cents=100))
    reply = await ana.say("era 1")
    assert reply.startswith("Compra parcelada: só dá para corrigir categoria ou descrição")


async def test_apagar_ultimo_asks_confirmation_and_only_yes_deletes(ana, parser, session):
    parser.add(expense(4500, "Mercado", merchant="Mercado"))
    await ana.say("gastei 45 no mercado")
    assert await ana.say("apagar último") == "Apagar R$ 45,00 · Mercado? Responda sim ou não"
    assert len(await txs(session)) == 1  # ainda não apagou
    assert await ana.say("não") == "Ok, não apaguei."
    assert len(await txs(session)) == 1
    await ana.say("apagar último")
    assert await ana.say("sim") == "🗑️ Apaguei: R$ 45,00 · Mercado · Mercado · hoje · Carteira"
    assert await txs(session) == []
    assert (await ana.say("sim")) == NOT_UNDERSTOOD  # "sim" solto não apaga mais nada


async def test_apagar_confirmation_expires_and_anything_else_cancels(ana, parser, session):
    parser.add(expense(4500, "Mercado", merchant="Mercado"))
    await ana.say("gastei 45 no mercado")
    await ana.say("apagar último")
    assert await ana.say("sim", ts=TS + timedelta(minutes=31)) == NOT_UNDERSTOOD
    assert len(await txs(session)) == 1  # expirou: o "sim" não apaga
    await ana.say("apagar último")
    parser.add(expense(1000, "Lazer", merchant="Cinema"))
    reply = await ana.say("gastei 10 no cinema")  # outra coisa: cancela e segue como mensagem nova
    assert reply.startswith("✅ R$ 10,00")
    assert len(await txs(session)) == 2
    assert (await ana.say("sim")) == NOT_UNDERSTOOD  # nada pendente
    assert len(await txs(session)) == 2


async def test_apagar_ultimo_deletes_only_my_chat_transaction(session, new_chat, parser):
    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    parser.add(expense(4500, "Mercado", merchant="Mercado"))
    await ana.say("gastei 45 no mercado")
    assert (
        await bia.say("apagar último")
        == "Não achei nenhum lançamento seu feito pelo chat para apagar."
    )
    assert len(await txs(session)) == 1  # a da Ana continua
    assert (await bia.say("sim")) == NOT_UNDERSTOOD
    assert len(await txs(session)) == 1


async def test_apagar_installment_group_and_resync_invoice(ana, parser, session):
    from app.domain.bills.models import Bill

    sp = ana.user.default_space_id
    await make_card(session, ana.user, sp, name="Visa")
    parser.add(
        intent(
            "lancar_parcelado",
            "Compras",
            amount_cents=30_000,
            installments=3,
            card_hint="visa",
            merchant="TV",
        )
    )
    await ana.say("tv 300 em 3x no visa")
    assert len(await txs(session)) == 3
    assert (
        await ana.say("apagar último") == "Apagar R$ 300,00 · TV (3 parcelas)? Responda sim ou não"
    )
    reply = await ana.say("sim")
    assert reply.endswith("(3 parcelas)") and await txs(session) == []
    amounts = list(await session.scalars(select(Bill.amount_cents).where(Bill.kind == "invoice")))
    assert amounts == [0, 0, 0]


async def test_a_deleted_transaction_confirmed_later_is_reported_politely(ana, parser, session):
    from app.domain.transactions.service import delete_transaction

    parser.add(expense(4500, "Mercado", merchant="Mercado"))
    await ana.say("gastei 45 no mercado")
    await ana.say("apagar último")
    [tx] = await txs(session)
    await delete_transaction(session, actor_id=ana.user.id, tx_id=tx.id)  # apagado pela web
    assert (await ana.say("sim")).startswith("Não encontrei isso")


async def test_pay_one_pending_bill_from_default_account(ana, session, parser):
    from app.domain.bills.service import create_bill

    sp = ana.user.default_space_id
    bill = await create_bill(
        session, actor_id=ana.user.id, space_id=sp, description="Luz", amount_cents=15_000,
        due_on=date(2026, 11, 30),
    )  # fmt: skip
    assert (await ana.say("paguei")).startswith("✅ Paguei R$ 150,00 · Luz · hoje · Carteira")
    await session.refresh(bill)
    assert bill.status == "paid" and parser.calls == []
    assert await ana.say("paguei") == "Não encontrei contas em aberto."
    assert (await ana.say("apagar último")).startswith("Apagar R$ 150,00 · Luz")
    reply = await ana.say("sim")  # desfaz o pagamento e reabre a conta
    assert reply.startswith("🗑️ Apaguei: R$ 150,00")
    await session.refresh(bill)
    assert bill.status == "open"


async def test_pay_many_lists_and_choose_second(ana, session, parser):
    from app.domain.bills.models import Bill
    from app.domain.bills.service import create_bill

    sp = ana.user.default_space_id
    for name, day in (("Luz", 28), ("Internet", 30)):
        await create_bill(
            session, actor_id=ana.user.id, space_id=sp, description=name, amount_cents=10_000,
            due_on=date(2026, 11, day),
        )  # fmt: skip
    reply = await ana.say("paguei")
    assert reply.startswith("Qual conta você pagou? Responda com o número:\n1) Luz")
    assert "2) Internet · vence 30/11 · R$ 100,00" in reply
    assert await ana.say("9") == "Responda com um dos números da lista."
    assert (await ana.say("2")).startswith("✅ Paguei R$ 100,00 · Internet")
    status = {b.description: b.status for b in await session.scalars(select(Bill))}
    assert status == {"Luz": "open", "Internet": "paid"}


async def test_pay_never_offers_other_peoples_bills(session, new_chat):
    from app.domain.bills.service import create_bill

    ana, bia = await new_chat("ana@x.com", "111"), await new_chat("bia@x.com", "222")
    await create_bill(
        session, actor_id=bia.user.id, space_id=bia.user.default_space_id, description="Aluguel",
        amount_cents=100_000, due_on=date(2026, 11, 30),
    )  # fmt: skip
    assert await ana.say("paguei") == "Não encontrei contas em aberto."


async def test_pay_invoice_from_wallet(ana, session):
    sp = ana.user.default_space_id
    card = await make_card(session, ana.user, sp, name="Visa")
    from app.domain.cards.service import register_card_purchase

    await register_card_purchase(
        session, actor_id=ana.user.id, space_id=sp, card_id=card.id, amount_cents=10_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    assert (await ana.say("paguei")).startswith("✅ Paguei R$ 100,00")
    assert await ana.say("faturas") == "Nenhuma fatura em aberto."


async def test_aporte_meta(ana, session, parser):
    from app.domain.goals.service import create_goal

    sp = ana.user.default_space_id
    await create_goal(
        session, actor_id=ana.user.id, space_id=sp, name="Viagem", target_cents=500_000,
        created_on=date(2026, 11, 1),
    )  # fmt: skip
    parser.add(intent("aporte_meta", amount_cents=50_000, goal_hint="viagem"))
    reply = await ana.say("guardei 500 na viagem")
    assert reply == (
        "✅ R$ 500,00 · Aporte na meta Viagem · hoje · Carteira\n"
        "Guardado: R$ 500,00 de R$ 5.000,00."
    )
    parser.add(intent("aporte_meta", amount_cents=1_000, goal_hint="carro"))
    assert (await ana.say("guardei 10 no carro")).startswith("Qual meta? Suas metas: Viagem.")
    parser.add(intent("aporte_meta", goal_hint="viagem"))
    assert await ana.say("guardei na viagem") == "Quanto você guardou? (ex.: 500)"
    assert (await ana.say("100")).startswith("✅ R$ 100,00 · Aporte na meta Viagem")


async def test_nova_conta_a_pagar(ana, session, parser):
    from app.domain.bills.models import Bill

    parser.add(
        intent(
            "nova_conta_a_pagar",
            amount_cents=12_000,
            description="Internet",
            occurred_on=date(2026, 12, 10),
        )
    )
    reply = await ana.say("conta de internet 120 vence dia 10")
    assert reply.startswith("📌 Anotei: Internet · R$ 120,00 · vence 10/12")
    bill = await session.scalar(select(Bill))
    assert (bill.amount_cents, bill.due_on, bill.status) == (12_000, date(2026, 12, 10), "open")
    parser.add(intent("nova_conta_a_pagar", amount_cents=12_000, description="Luz"))
    assert (await ana.say("conta de luz 120")).startswith("Para anotar uma conta a pagar preciso")

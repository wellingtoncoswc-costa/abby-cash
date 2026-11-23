from sqlalchemy import select

from app.assistant.flows.common import ask, remaining_of
from app.assistant.flows.payment import choose_account
from app.assistant.intents import ParsedIntent
from app.assistant.replies import NO_ACCOUNT, ZERO, options_text
from app.assistant.turn import Draft, Pay, Turn
from app.core.money import format_brl
from app.domain.bills.models import Bill
from app.domain.payments import pay_bill, pay_invoice
from app.domain.spaces.models import SpaceMember


async def pending(t: Turn) -> list[tuple[Bill, int]]:
    """Contas a pagar (e faturas) em aberto dos espaços do usuário, com o que falta pagar."""
    mine = select(SpaceMember.space_id).where(SpaceMember.user_id == t.user_id)
    bills = await t.session.scalars(
        select(Bill)
        .where(Bill.space_id.in_(mine), Bill.status != "paid")
        .order_by(Bill.due_on)
        .limit(10)
    )
    out = [(b, await remaining_of(t, b)) for b in bills]
    return [(b, rem) for b, rem in out if rem > 0]


async def start(t: Turn, p: ParsedIntent) -> str:
    """ponytail: sem contexto de lembrete (M5); 0 -> aviso, 1 -> quita, várias -> lista."""
    if p.amount_cents is not None and p.amount_cents <= 0:
        return ZERO
    items = await pending(t)
    if not items:
        return "Não encontrei contas em aberto."
    if len(items) == 1:
        bill = items[0][0]
        return await run(t, Draft(action="pay", p=p, space_id=bill.space_id, bill_id=bill.id))
    options = [
        Pay(
            type="bill", id=b.id,
            label=f"{b.description} · vence {b.due_on:%d/%m} · {format_brl(rem)}",
        )
        for b, rem in items
    ]  # fmt: skip
    d = Draft(action="pay", p=p, space_id=items[0][0].space_id, options=options)
    return await ask(
        t, d, "pick_bill", options_text("Qual conta você pagou?", [o.label for o in options])
    )


async def run(t: Turn, d: Draft) -> str:
    """Quita a conta escolhida: origem = dica -> padrão -> pergunta; valor = o que falta."""
    bill = await t.session.get(Bill, d.bill_id)
    assert bill is not None
    description, due_invoice, space_id = bill.description, bill.invoice_id, bill.space_id
    ctx = await t.context(space_id)  # exige ser membro do espaço da conta
    if d.payment is None:
        hints = [d.p.account_hint] if d.p.account_hint else []
        chosen, options = choose_account(ctx, hints)
        if chosen is None:
            if not options:
                return NO_ACCOUNT
            d.options = options
            return await ask(
                t, d, "payment", options_text("De qual conta saiu?", [o.label for o in options])
            )
        d.payment = chosen
    if due_invoice is not None:
        amount = d.p.amount_cents or await remaining_of(t, bill)
        tx = await pay_invoice(
            t.session, actor_id=t.user_id, invoice_id=due_invoice, account_id=d.payment.id,
            paid_on=t.today, amount_cents=amount, origin=t.channel,
            source_message_id=t.message_id,
        )  # fmt: skip
    else:
        tx = await pay_bill(
            t.session, actor_id=t.user_id, bill_id=bill.id, account_id=d.payment.id,
            paid_on=t.today, amount_cents=d.p.amount_cents,
            origin=t.channel, source_message_id=t.message_id,
        )  # fmt: skip
    left = await remaining_of(t, bill)
    tail = f"\nFalta {format_brl(left)}." if left > 0 else ""
    return (
        f"✅ Paguei {format_brl(tx.amount_cents)} · {description} · hoje · {d.payment.label}{tail}"
    )

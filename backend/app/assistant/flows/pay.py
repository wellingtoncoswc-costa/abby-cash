import difflib
import re
from uuid import UUID

from sqlalchemy import delete, select

from app.assistant.flows.common import ask, remaining_of
from app.assistant.flows.payment import choose_account
from app.assistant.intents import ParsedIntent
from app.assistant.models import ConversationState
from app.assistant.replies import NO_ACCOUNT, ZERO, options_text
from app.assistant.turn import Draft, Pay, Turn
from app.core.money import format_brl
from app.core.text import fold
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


_GENERIC = {"paguei", "pago", "quitei", "pagar", "conta", "contas"}


def mentions(text: str, p: ParsedIntent, description: str) -> bool:
    """O texto (ou a dica do modelo) cita a conta? Aproximado, sem acento/caixa."""
    said = set(re.findall(r"\w{3,}", fold(f"{text} {p.description or ''} {p.merchant or ''}")))
    words = set(re.findall(r"\w{3,}", fold(description))) - _GENERIC
    return any(difflib.get_close_matches(w, words, n=1, cutoff=0.8) for w in said - _GENERIC)


async def take_reminded(t: Turn) -> UUID | None:
    """Conta do último lembrete (24 h, qualquer canal); consome o contexto."""
    row = await t.session.scalar(
        delete(ConversationState)
        .where(
            ConversationState.user_id == t.user_id, ConversationState.kind == "reminder",
            ConversationState.expires_at > t.now,
        )
        .returning(ConversationState.data)
    )  # fmt: skip
    await t.session.commit()
    return UUID(row["last_reminded_bill_id"]) if row else None


async def start(t: Turn, p: ParsedIntent, text: str = "") -> str:
    """ponytail: 0 -> aviso, 1 -> quita se o
    texto cita a conta, senão pergunta; várias -> lista."""
    if p.amount_cents is not None and p.amount_cents <= 0:
        return ZERO
    items = await pending(t)
    if items and (remembered := await take_reminded(t)) is not None:
        for b, _ in items:
            if b.id == remembered:  # acabou de ser lembrada: paga direto
                return await run(t, Draft(action="pay", p=p, space_id=b.space_id, bill_id=b.id))
    if len(items) > 1 and "fatura" in fold(text):
        items = [i for i in items if i[0].invoice_id] or items
    if not items:
        return "Não encontrei contas em aberto."
    if len(items) == 1:
        bill, rem = items[0]
        d = Draft(action="pay", p=p, space_id=bill.space_id, bill_id=bill.id)
        if mentions(text, p, bill.description):
            return await run(t, d)
        question = f"Pagar {bill.description} {format_brl(rem)}? Responda sim ou não"
        return await ask(t, d, "confirm", question)
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
    if bill is None:
        return "Não encontrei essa conta."
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

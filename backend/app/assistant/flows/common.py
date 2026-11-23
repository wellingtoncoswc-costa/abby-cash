from uuid import UUID

from sqlalchemy import update

from app.assistant.state import set_state
from app.assistant.turn import Draft, Turn
from app.domain.bills.models import Bill
from app.domain.bills.status import bill_paid_cents
from app.domain.cards.service import invoice_remaining
from app.domain.transactions.models import Transaction


async def ask(t: Turn, d: Draft, kind: str, text: str) -> str:
    """Guarda a ação em andamento e devolve a pergunta; a próxima mensagem retoma (30 min)."""
    await set_state(
        t.session, t.user_id, t.channel, kind, {"draft": d.model_dump(mode="json")}, t.now
    )
    return text


async def tag_origin(t: Turn, tx_id: UUID) -> None:
    """Pagamentos e aportes nascem com origem "web" no domínio; pelo chat passam a ser do canal
    (e guardam a mensagem), para o "apagar último" achá-los."""
    await t.session.execute(
        update(Transaction)
        .where(Transaction.id == tx_id)
        .values(origin=t.channel, source_message_id=t.message_id)
    )
    await t.session.commit()


async def remaining_of(t: Turn, bill: Bill) -> int:
    if bill.invoice_id is not None:
        return await invoice_remaining(t.session, bill.invoice_id)
    return bill.amount_cents - await bill_paid_cents(t.session, bill.id)

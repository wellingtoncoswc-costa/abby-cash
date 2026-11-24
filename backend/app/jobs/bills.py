from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.assistant.models import ConversationState
from app.channels.sender import notify_user
from app.core.config import get_settings
from app.core.dates import add_months, local_today
from app.core.db import SessionLocal
from app.core.money import format_brl
from app.domain.bills.models import Bill, BillReminderSent
from app.domain.bills.recurrence import Recurrence, generate_occurrences
from app.domain.bills.status import bill_paid_cents
from app.domain.cards.models import Invoice
from app.domain.cards.service import invoice_remaining, sync_invoice_bill
from app.domain.spaces.models import SpaceMember
from app.domain.users.models import User
from app.jobs.scheduler import isolated

REMINDER_TTL = timedelta(hours=24)
_TEXT = {
    "day_before": "🔔 Amanhã vence: {d} · {v}.",
    "due": "🔔 Hoje vence: {d} · {v}.",
    "overdue": '⚠️ Venceu ontem: {d} · {v}. Responda "paguei" para quitar.',
}
_OFFSET = {1: "day_before", 0: "due", -1: "overdue"}  # vencimento - hoje


async def _remember(user_id: UUID, channel: str, bill_ids: list[UUID], now: datetime) -> None:
    """Contexto do "paguei" (24 h); não pisa em pergunta pendente ainda viva."""
    values = {"kind": "reminder", "data": {"last_reminded_bill_ids": [str(i) for i in bill_ids]},
              "expires_at": now + REMINDER_TTL}  # fmt: skip
    async with SessionLocal() as s:
        await s.execute(
            insert(ConversationState)
            .values(user_id=user_id, channel=channel, **values)
            .on_conflict_do_update(
                index_elements=["user_id", "channel"],
                set_=values,
                where=(ConversationState.kind == "reminder")
                | (ConversationState.expires_at <= now),
            )  # fmt: skip
        )
        await s.commit()


async def _remind_user(user_id: UUID, now: datetime) -> None:
    async with SessionLocal() as s:
        user = await s.get(User, user_id)
        assert user is not None
        local = now.astimezone(ZoneInfo(user.tz))
        if local.time() < user.reminder_time:
            return
        today = local.date()
        mine = select(SpaceMember.space_id).where(SpaceMember.user_id == user_id)
        bills = list(
            await s.scalars(
                select(Bill)
                .where(
                    Bill.space_id.in_(mine), Bill.status != "paid",
                    Bill.due_on.in_([today + timedelta(days=o) for o in _OFFSET]),
                    (Bill.responsible_user_id == user_id) | Bill.responsible_user_id.is_(None),
                )
                .order_by(Bill.due_on)
            )
        )  # fmt: skip
        todo: list[tuple[UUID, str, str, str]] = []
        for b in bills:
            left = (
                await invoice_remaining(s, b.invoice_id)
                if b.invoice_id
                else b.amount_cents - await bill_paid_cents(s, b.id)
            )
            if left > 0:
                kind = _OFFSET[(b.due_on - today).days]
                todo.append((b.id, kind, b.description, format_brl(left)))
    sent: dict[str, list[UUID]] = {}
    for bill_id, kind, description, value in todo:
        async with SessionLocal() as s:  # insere primeiro: execuções concorrentes não duplicam
            claimed = await s.scalar(
                insert(BillReminderSent)
                .values(bill_id=bill_id, user_id=user_id, kind=kind)
                .on_conflict_do_nothing(constraint="uq_bill_reminder_once")
                .returning(BillReminderSent.id)
            )
            await s.commit()
            if claimed is None:
                continue
            channel = await notify_user(user_id, _TEXT[kind].format(d=description, v=value))
            if channel is None:  # não entregou: libera para o próximo ciclo
                await s.execute(delete(BillReminderSent).where(BillReminderSent.id == claimed))
                await s.commit()
                continue
        sent.setdefault(channel, []).append(bill_id)
    for channel, ids in sent.items():
        await _remember(user_id, channel, ids, now)


async def send_bill_reminders(
    ctx: dict[str, Any] | None = None, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    async with SessionLocal() as s:
        ids = list(await s.scalars(select(User.id)))
    for uid in ids:
        await isolated("reminder", lambda uid=uid: _remind_user(uid, now))  # type: ignore[misc]


async def _generate(source_id: UUID, today: date) -> None:
    async with SessionLocal() as s:
        src = await s.get(Bill, source_id)
        assert src is not None and src.recurrence_rule is not None
        rule = Recurrence.from_json(src.recurrence_rule)
        end = add_months(today, 3)
        months = (end.year - src.due_on.year) * 12 + end.month - src.due_on.month + 1
        rows = [
            {
                "space_id": src.space_id, "kind": "manual", "description": src.description,
                "amount_cents": src.amount_cents, "due_on": d, "category_id": src.category_id,
                "responsible_user_id": src.responsible_user_id, "status": "open",
                "recurrence_id": src.id,
            }
            for d in generate_occurrences(rule, src.due_on, months)
            if today <= d <= end
        ]  # fmt: skip
        if rows:
            await s.execute(
                insert(Bill)
                .values(rows)
                .on_conflict_do_nothing(constraint="uq_bills_recurrence_due")
            )
            await s.commit()


async def _refresh(invoice_id: UUID) -> None:
    async with SessionLocal() as s:
        inv = await s.get(Invoice, invoice_id)
        if inv is not None:
            await sync_invoice_bill(s, inv)
            await s.commit()


async def daily_bills_job(ctx: dict[str, Any] | None = None, today: date | None = None) -> None:
    """Gera as ocorrências recorrentes (3 meses) e atualiza os espelhos das faturas abertas."""
    today = today or local_today(get_settings().DEFAULT_TZ)
    async with SessionLocal() as s:
        sources = list(
            await s.scalars(
                select(Bill.id).where(
                    Bill.recurrence_rule.is_not(None), Bill.recurrence_id == Bill.id
                )
            )
        )
        invoices = list(await s.scalars(select(Invoice.id).where(Invoice.closing_on >= today)))
    for sid in sources:
        await isolated("recurrence", lambda sid=sid: _generate(sid, today))  # type: ignore[misc]
    for iid in invoices:
        await isolated("invoice", lambda iid=iid: _refresh(iid))  # type: ignore[misc]

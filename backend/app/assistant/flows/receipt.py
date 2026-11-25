import logging
import re
from datetime import date
from typing import Any
from uuid import UUID

from app.ai.receipt import ReceiptData
from app.assistant.amounts import ZERO_OR_NEG, parse_bare_amount
from app.assistant.flows import edit
from app.assistant.flows.common import ask
from app.assistant.hints import BadDate, resolve_date
from app.assistant.intents import ParsedIntent
from app.assistant.replies import FUTURE_DATE, ZERO
from app.assistant.resolve import resolve_hint
from app.assistant.turn import Draft, Turn
from app.channels.base import MediaTooLarge
from app.channels.registry import get_adapter
from app.core.money import format_brl
from app.core.text import fold
from app.domain.attachments import MAX_BYTES, find_attachment, read_file, save_image

log = logging.getLogger(__name__)
GO: Any = object()  # `step`: "sim" explícito, siga e grave
TOO_BIG = "Esse arquivo é grande demais (máximo 10 MB)."
NOT_IMAGE = "Só consigo ler foto de comprovante (JPEG, PNG ou WebP)."
FAIL = "Não consegui baixar a imagem. Tente enviar de novo."
ASK_AMOUNT = "Não consegui ler o valor do comprovante. Quanto foi? (ex.: 45 ou 45,50)"
_LEAD = re.compile(r"^\s*(?:é|e|foi|era|são|sao)\s+", re.I)


def _confirm_text(t: Turn, d: Draft) -> str:
    p = d.p
    assert p.amount_cents is not None
    day = (p.occurred_on or t.today).strftime("%d/%m")
    parts = [f"Lançar {format_brl(p.amount_cents)}", *([p.merchant] if p.merchant else []), day]
    return " · ".join(parts) + '? Responda "sim" ou corrija'


async def prompt(t: Turn, d: Draft) -> str:
    """Pergunta de confirmação (ou o valor, se não foi lido); o estado é sempre `receipt`."""
    text = _confirm_text(t, d) if d.p.amount_cents else ASK_AMOUNT
    return await ask(t, d, "receipt", text)


async def start(t: Turn, row: Any, reader: Any, space_id: UUID, private: bool) -> str:
    """Foto -> anexo salvo -> leitura -> pergunta. NUNCA grava lançamento aqui."""
    att = await find_attachment(t.session, t.channel, t.message_id)  # reentrega: reaproveita
    if att is None:
        try:
            data, _ = await get_adapter(t.channel).download_media(row.media_ref, MAX_BYTES)
        except MediaTooLarge:
            return TOO_BIG
        except Exception as e:
            log.warning("receipt download failed (%s)", type(e).__name__)
            return FAIL
        att = await save_image(
            t.session, space_id=space_id, origin=t.channel, source_message_id=t.message_id,
            data=data,
        )  # fmt: skip
        if att is None:
            return NOT_IMAGE
    try:
        if reader is None:
            raise RuntimeError("no receipt reader configured")
        data_ = await reader.read(read_file(att), att.mime, space_id)
    except Exception as e:  # ilegível/IA fora: pergunta o valor
        log.warning("receipt read failed (%s)", type(e).__name__)
        data_ = ReceiptData(confidence=0)
    day = data_.occurred_on if data_.occurred_on and data_.occurred_on <= t.today else None
    p = ParsedIntent.of(
        "lancar_despesa", amount_cents=data_.amount_cents, merchant=data_.merchant,
        description=data_.merchant, occurred_on=day, account_hint=data_.payment_hint,
    )  # fmt: skip
    d = Draft(action="launch", p=p, space_id=space_id, private=private, attachment_id=att.id)
    return await prompt(t, d)


def _correction(text: str, today: date) -> dict[str, Any] | None:
    if fields := edit.parse_correction(text, today):
        return fields
    s = _LEAD.sub("", text)
    if (cents := parse_bare_amount(s)) is not None:
        return {"amount_cents": cents}
    if ZERO_OR_NEG.fullmatch(s.strip()):
        return {"amount_cents": 0}
    try:
        day = resolve_date(s, today)
    except BadDate:
        return None
    return {"occurred_on": day} if day else None


async def step(t: Turn, d: Draft, text: str, reply: str | None) -> Any:
    """Resposta ao rascunho do comprovante: GO (sim), nova pergunta (valor/correção) ou None
    (era outra mensagem)."""
    p = d.p
    if p.amount_cents is None:  # só o valor destrava
        amount = parse_bare_amount(text)
        if amount is None:
            return ZERO + " Quanto foi?" if ZERO_OR_NEG.fullmatch(text.strip()) else None
        p.amount_cents = amount
        return await prompt(t, d)
    if reply == "sim":
        return GO
    fields = _correction(text, t.today)
    if not fields:
        return None
    if "amount_cents" in fields:
        if not fields["amount_cents"]:
            return ZERO + " " + _confirm_text(t, d)
        p.amount_cents = fields["amount_cents"]
    if day := fields.get("occurred_on"):
        if day > t.today:
            return FUTURE_DATE
        p.occurred_on = day
    if "description" in fields:
        p.description = p.merchant = fields["description"]
    if name := fields.get("category_name"):
        ctx = await t.context(d.space_id)
        expense = [c for c in ctx.categories if c.kind == "expense"]
        best = resolve_hint(name, [c.name for c in expense])
        if best is None:
            return f'Não achei a categoria "{fold(name)[:40]}". Responda "sim" ou corrija.'
        p.category_index = 1 + ctx.categories.index(next(c for c in expense if c.name == best))
    return await prompt(t, d)

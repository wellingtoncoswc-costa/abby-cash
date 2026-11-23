import asyncio
import logging
import re
import traceback
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.amounts import ZERO_OR_NEG, parse_bare_amount
from app.assistant.flows import edit, extras, launch, pay, query
from app.assistant.flows.payment import pick_option
from app.assistant.hints import Hints, extract_hints
from app.assistant.intents import Intent, ParsedIntent
from app.assistant.replies import (
    AI_DOWN,
    HELP,
    MEDIA,
    NO_FAMILY,
    NOT_UNDERSTOOD,
    ZERO,
    domain_error_text,
    http_error_text,
)
from app.assistant.shortcuts import answer, try_shortcut
from app.assistant.state import clear_state, get_state
from app.assistant.turn import Draft, Turn
from app.channels.registry import get_adapter
from app.core.config import get_settings
from app.core.dates import to_local_date
from app.core.money import format_brl
from app.core.db import SessionLocal
from app.core.text import fold
from app.domain.channels.linking import find_user_by_link, link_with_code
from app.domain.channels.models import InboundMessage
from app.domain.errors import DomainError
from app.domain.spaces.models import Space, SpaceMember

STALE = timedelta(minutes=5)
log = logging.getLogger(__name__)

UNLINKED = (
    "Oi! Eu sou a Abby Cash, assistente de finanças. Para usar este chat, abra o painel web, "
    "vá em Canais, escolha Vincular Telegram e envie aqui o código de 6 dígitos "
    "(ou toque no link que o painel mostra)."
)
INVALID_CODE = "Código inválido ou expirado. Gere um novo no painel web (Canais)."
TOO_MANY = "Muitas tentativas. Tente de novo em 1 hora."
ALREADY_LINKED = "Este Telegram já está vinculado a outra conta."
LINKED_OK = (
    "✅ Telegram vinculado, {name}! Agora é só me mandar seus gastos, "
    "por exemplo: gastei 45 no mercado."
)
FAILED = "Tive um problema ao processar sua mensagem. Tente de novo em instantes."

_CODE = re.compile(r"(?:/start(?:@\w+)?\s+)?([0-9]{6})", re.ASCII | re.IGNORECASE)
_LAUNCH = {"lancar_despesa", "lancar_receita", "lancar_parcelado"}
_NEEDS_AMOUNT = _LAUNCH | {"corrigir", "pagar_conta", "nova_conta_a_pagar", "aporte_meta"}
_INCOME_VERBS = re.compile(r"\s*(recebi|ganhei|entrou|caiu)\b")
_LEADING_VERB = re.compile(r"^\s*(gastei|paguei|comprei|recebi|ganhei|foi|deu)\b\s*", re.I)


async def claim(session: AsyncSession, inbound_id: UUID) -> bool:
    """received -> processing de forma atômica: só um worker processa cada mensagem.
    Também retoma 'processing' parado há mais de 5 min (worker que caiu)."""
    got = await session.scalar(
        update(InboundMessage)
        .where(
            InboundMessage.id == inbound_id,
            or_(
                InboundMessage.status == "received",
                and_(
                    InboundMessage.status == "processing",
                    InboundMessage.updated_at < func.now() - STALE,
                ),
            ),
        )
        .values(status="processing", updated_at=func.now())
        .returning(InboundMessage.id)
    )
    await session.commit()
    return got is not None


async def unlinked(session: AsyncSession, channel: str, external_user_id: str, text: str) -> str:
    """Remetente desconhecido: só instrução fixa (ou vínculo, se mandou um código). Nada é gravado
    no domínio."""
    m = _CODE.fullmatch(text.strip())
    if not m:
        return UNLINKED
    try:
        user = await link_with_code(
            session, channel=channel, external_user_id=external_user_id, code=m.group(1)
        )
    except DomainError as e:
        return TOO_MANY if str(e) == "too_many_attempts" else ALREADY_LINKED
    if user is None:
        return INVALID_CODE
    return LINKED_OK.format(name=user.name.split()[0])


def merge_hints(p: ParsedIntent, h: Hints) -> tuple[ParsedIntent, str | None]:
    """O determinístico vale mais que o LLM em etiquetas, datas e parcelas; o valor do LLM vale
    se o modelo não o inventou: sem ele, o do texto; com parcelas, "3x de 500" dá o total exato e,
    se o valor do modelo não aparece entre os números do texto mas só há um, o do texto vale (com
    aviso). `private` do modelo é só dica: quem decide o espaço é a etiqueta do texto."""
    warn = None
    p.private = h.private
    if p.intent in _NEEDS_AMOUNT:
        if p.amount_cents is None:
            p.amount_cents = h.amount_cents
        elif h.installments and h.amount_cents is not None:
            if h.total_exact:
                p.amount_cents = h.amount_cents
            elif p.amount_cents not in h.amounts and len(h.amounts) == 1:
                p.amount_cents = h.amounts[0]
                warn = f"Usei o valor {format_brl(h.amounts[0])} da sua mensagem."
    if p.intent in _LAUNCH:
        p.occurred_on = h.occurred_on or p.occurred_on
        p.installments = h.installments or p.installments
        many = (p.installments or 1) > 1
        if p.intent != "lancar_receita":
            p.intent = "lancar_parcelado" if many else "lancar_despesa"
    return p, warn


def fallback_launch(text: str, h: Hints) -> ParsedIntent | None:
    """IA fora do ar: valor + resto como descrição, categoria Outros (spec 9)."""
    if h.amount_cents is None:
        return None
    rest = re.sub(r"#\w+", " ", text)
    rest = re.sub(r"(?i)(?:r\$\s*)?\d[\d.,]*(?:\s*(?:reais|real))?", " ", rest, count=1)
    description = " ".join(_LEADING_VERB.sub("", rest).split()) or None
    intent: Intent = "lancar_despesa"
    if _INCOME_VERBS.match(fold(text)):
        intent = "lancar_receita"
    elif h.installments:
        intent = "lancar_parcelado"
    return ParsedIntent.of(
        intent, amount_cents=h.amount_cents, description=description, occurred_on=h.occurred_on,
        installments=h.installments,
    )  # fmt: skip


async def target_space(t: Turn, h: Hints) -> tuple[UUID | None, str | None]:
    """#pessoal -> espaço pessoal; #familia -> espaço familiar; senão o espaço padrão. Sempre um
    espaço do próprio remetente."""
    s = t.session
    if h.family and not h.private:
        sid = await s.scalar(
            select(Space.id)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(SpaceMember.user_id == t.user_id, Space.type == "family")
        )
        return (sid, None) if sid else (None, NO_FAMILY)
    if not h.private and t.default_space_id is not None:
        return t.default_space_id, None
    sid = await s.scalar(
        select(Space.id).where(Space.owner_id == t.user_id, Space.type == "personal")
    )
    return (sid, None) if sid else (None, "Não achei seu espaço pessoal.")


async def run_draft(t: Turn, d: Draft) -> str:
    if d.action == "pay":
        return await pay.run(t, d)
    if d.action == "aporte":
        return await extras.run_aporte(t, d)
    return await launch.run(t, d)


async def resume(t: Turn, text: str) -> str | None:
    """Responde a uma pergunta pendente. None = a mensagem não era a resposta (o estado foi
    descartado e ela segue como mensagem nova)."""
    state = await get_state(t.session, t.user_id, t.channel, t.now)
    if state is None:
        return None
    kind, data, reply = state.kind, dict(state.data), answer(text)
    if reply == "cancelar":
        await clear_state(t.session, t.user_id, t.channel)
        return "Ok, cancelei."
    if kind == "correct":
        await clear_state(t.session, t.user_id, t.channel)
        fields = edit.parse_correction(text, t.today)
        return await edit.apply_correction(t, fields) if fields else None
    if kind == "delete":  # só um "sim" explícito apaga; "não" cancela; outra coisa é mensagem nova
        await clear_state(t.session, t.user_id, t.channel)
        if reply == "sim":
            return await edit.confirm_delete(t, UUID(data["tx_id"]))
        return "Ok, não apaguei." if reply == "nao" else None
    d = Draft.model_validate(data["draft"])
    if kind == "amount":
        amount = parse_bare_amount(text)
        if amount is None:
            if ZERO_OR_NEG.fullmatch(text.strip()):  # parece valor, mas é zero/negativo
                return ZERO + " Quanto foi?"
            await clear_state(t.session, t.user_id, t.channel)
            return None
        d.p.amount_cents = amount
    elif kind == "confirm":
        if reply != "sim":
            await clear_state(t.session, t.user_id, t.channel)
            return "Ok, não lancei." if reply == "nao" else None
        d.confirmed = True
    else:  # payment | pick_bill
        picked = pick_option(d.options, text)
        if picked is None:
            if re.fullmatch(r"\d{1,2}", text.strip()):
                return "Responda com um dos números da lista."
            await clear_state(t.session, t.user_id, t.channel)
            return None
        d.options = []
        if kind == "pick_bill":
            d.bill_id = picked.id
        else:
            d.payment = picked
    await clear_state(t.session, t.user_id, t.channel)
    return await run_draft(t, d)


async def interpret(
    t: Turn, text: str, h: Hints, space_id: UUID
) -> tuple[ParsedIntent | None, str | None]:
    """Atalho sem LLM; senão LLM + determinístico; se o LLM falhar, o fallback simples."""
    shortcut = try_shortcut(re.sub(r"#\w+", " ", text))  # "#pessoal gastos" também é atalho
    if shortcut is not None:
        return shortcut, None
    try:
        if t.parser is None:
            raise RuntimeError("no parser configured")
        ctx = await t.context(space_id)
        timeout = get_settings().AI_TIMEOUT_S + 5
        return merge_hints(await asyncio.wait_for(t.parser.parse(text, ctx), timeout), h)
    except HTTPException:
        raise  # isolamento: não é falha da IA
    except Exception as e:
        log.warning("intent parser failed (%s); using the plain fallback", type(e).__name__)
        return fallback_launch(text, h), AI_DOWN


async def fresh(t: Turn, text: str) -> str:
    h = extract_hints(text, t.today)
    space_id, error = await target_space(t, h)
    if space_id is None:
        return error or NOT_UNDERSTOOD
    p, warn = await interpret(t, text, h, space_id)
    if p is None:
        return NOT_UNDERSTOOD
    t.intent = p.intent
    if p.intent in _NEEDS_AMOUNT and p.amount_cents is None and ZERO_OR_NEG.search(text):
        p.amount_cents = 0  # sem validação: os fluxos recusam e perguntam de novo
    match p.intent:
        case "lancar_despesa" | "lancar_receita" | "lancar_parcelado":
            return await launch.start(t, p, space_id, h, warn)
        case "corrigir":
            return await edit.corrigir(t, p, space_id)
        case "apagar":
            return await edit.apagar(t)
        case "pagar_conta":
            return await pay.start(t, p)
        case "nova_conta_a_pagar":
            return await extras.nova_conta(t, p, space_id)
        case "aporte_meta":
            return await extras.aporte(t, p, space_id)
        case "consultar_gastos":
            return await query.gastos(t, p, space_id)
        case "consultar_teto":
            return await query.teto(t, space_id)
        case "consultar_saldo":
            return await query.saldo(t)
        case "consultar_faturas":
            return await query.faturas(t)
        case "ajuda":
            return HELP
        case _:
            return NOT_UNDERSTOOD


async def converse(t: Turn, text: str) -> str:
    return await resume(t, text) or await fresh(t, text)


async def handle(session: AsyncSession, ctx: dict[str, Any], row: InboundMessage) -> str | None:
    user = await find_user_by_link(session, row.channel, row.external_user_id)
    if user is None:
        return await unlinked(session, row.channel, row.external_user_id, row.text or "")
    row.user_id = user.id
    if row.media_kind is not None:  # áudio e foto entram no M6; a legenda não grava nada
        return MEDIA
    text = (row.text or "").strip()
    if not text:
        return None
    t = Turn(
        session=session, user_id=user.id, tz=user.tz, default_space_id=user.default_space_id,
        channel=row.channel, message_id=row.external_message_id, now=row.received_at,
        today=to_local_date(row.received_at, user.tz), parser=ctx.get("parser"),
    )  # fmt: skip
    reply = await converse(t, text)
    row.result = {"intent": t.intent}
    return reply


def _where(e: BaseException) -> str:
    """Tipo e pilha, sem a mensagem da exceção (pode conter o texto do usuário)."""
    return type(e).__name__ + "\n" + "".join(traceback.format_tb(e.__traceback__))


async def handle_inbound(ctx: dict[str, Any], inbound_id: UUID) -> None:
    async with SessionLocal() as session:
        if not await claim(session, inbound_id):
            return  # já processada (reentrega do ARQ, corrida)
        row = await session.get(InboundMessage, inbound_id)
        assert row is not None
        channel, external_user_id = row.channel, row.external_user_id  # escalares: rollback expira
        status = "processed"
        try:
            reply = await handle(session, ctx, row)
            await session.commit()
        except DomainError as e:
            await session.rollback()
            reply = domain_error_text(str(e))
        except HTTPException as e:
            await session.rollback()
            reply = http_error_text(e.status_code)
        except Exception as e:
            log.error("process_inbound failed: %s", _where(e))
            await session.rollback()
            reply, status = FAILED, "failed"
        row = await session.get(InboundMessage, inbound_id, populate_existing=True)
        assert row is not None
        row.status = status
        await session.commit()
        if reply:
            try:
                await get_adapter(channel).send_text(external_user_id, reply)
            except Exception as e:
                log.warning("send_text failed (%s)", type(e).__name__)

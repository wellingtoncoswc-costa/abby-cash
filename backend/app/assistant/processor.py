import asyncio
import logging
import re
import traceback
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.usage import over_budget, record_ai_usage
from app.assistant.amounts import ZERO_OR_NEG, parse_bare_amount
from app.assistant.flows import edit, extras, launch, pay, query, receipt
from app.assistant.flows.common import already_done
from app.assistant.flows.payment import pick_option
from app.assistant.hints import Hints, extract_hints
from app.assistant.intents import Intent, ParsedIntent
from app.assistant.replies import (
    AI_DOWN,
    ALREADY,
    ALREADY_HANDLED,
    BAD_DATE,
    DIGEST_OFF,
    DIGEST_ON,
    HELP,
    NO_FAMILY,
    NOT_UNDERSTOOD,
    OVER_BUDGET,
    OVER_BUDGET_MEDIA,
    RATE_LIMITED,
    ZERO,
    domain_error_text,
    http_error_text,
)
from app.assistant.shortcuts import answer, digest_toggle, try_shortcut
from app.assistant.state import clear_state, get_state
from app.assistant.turn import Draft, Turn
from app.channels.base import MediaTooLarge
from app.channels.registry import get_adapter
from app.core.config import get_settings
from app.core.dates import to_local_date
from app.core.db import SessionLocal, engine
from app.core.money import format_brl
from app.core.redis import incr_ttl, redis
from app.core.text import fold
from app.domain.attachments import MAX_BYTES, discard_draft_attachment
from app.domain.channels.linking import find_user_by_link, link_with_code
from app.domain.channels.models import InboundMessage
from app.domain.errors import DomainError
from app.domain.spaces.models import Space, SpaceMember
from app.domain.users.models import User

STALE = timedelta(minutes=5)
log = logging.getLogger(__name__)

_UNLINKED = (
    "Oi! Eu sou a Abby Cash, assistente de finanças. Para usar este chat, abra o painel web, "
    "vá em Canais, escolha Vincular {chat} e envie aqui o código de 6 dígitos "
    "(ou toque no link que o painel mostra)."
)
_ALREADY_LINKED = "Este {chat} já está vinculado a outra conta."
_LINKED_OK = (
    "✅ {chat} vinculado, {{name}}! Agora é só me mandar seus gastos, "
    "por exemplo: gastei 45 no mercado."
)
INVALID_CODE = "Código inválido ou expirado. Gere um novo no painel web (Canais)."
TOO_MANY = "Muitas tentativas. Tente de novo em 1 hora."
UNLINKED = _UNLINKED.format(chat="Telegram")
UNLINKED_TTL_S = 86400
AUDIO_FAIL = "Não consegui ouvir o áudio, pode escrever?"
TOO_BIG = receipt.TOO_BIG
FAILED = "Tive um problema ao processar sua mensagem. Tente de novo em instantes."

_CODE = re.compile(r"(?:/start(?:@\w+)?\s+)?([0-9]{6})", re.ASCII | re.IGNORECASE)
_LAUNCH = {"lancar_despesa", "lancar_receita", "lancar_parcelado"}
_NEEDS_AMOUNT = _LAUNCH | {"corrigir", "pagar_conta", "nova_conta_a_pagar", "aporte_meta"}
_WRITES = {"corrigir", "apagar", "pagar_conta", "nova_conta_a_pagar", "aporte_meta"}
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


async def unlinked(
    session: AsyncSession, channel: str, external_user_id: str, text: str
) -> str | None:
    """Remetente desconhecido: só instrução fixa (ou vínculo, se mandou um código). Nada é gravado
    no domínio."""
    chat = "WhatsApp" if channel == "whatsapp_evolution" else "Telegram"
    m = _CODE.fullmatch(text.strip())
    if not m:
        # estranho que insiste não vira spam: instrução no máximo 1x/24h por (canal, remetente)
        first = await redis.set(
            f"unlinked_reply:{channel}:{external_user_id}", 1, nx=True, ex=UNLINKED_TTL_S
        )
        return _UNLINKED.format(chat=chat) if first else None
    try:
        user = await link_with_code(
            session, channel=channel, external_user_id=external_user_id, code=m.group(1)
        )
    except DomainError as e:
        return TOO_MANY if str(e) == "too_many_attempts" else _ALREADY_LINKED.format(chat=chat)
    if user is None:
        return INVALID_CODE
    return _LINKED_OK.format(chat=chat).format(name=user.name.split()[0])


def merge_hints(p: ParsedIntent, h: Hints) -> ParsedIntent:
    """O determinístico vale mais que o LLM em etiquetas, datas e parcelas; o valor do LLM vale,
    exceto com parcelas (aí o total da mensagem manda: "3x de 500") ou se ele não achou nenhum.
    `private` do modelo é só dica: quem decide o espaço é a etiqueta do texto."""
    p.private = h.private
    if p.intent in _NEEDS_AMOUNT and h.amount_cents is not None:
        # os dígitos digitados valem mais que o modelo, salvo se o valor dele aparece no texto
        # ("uber 2 pessoas 23"); `interpret` avisa quando troca um valor do modelo
        if p.amount_cents is None or h.installments or p.amount_cents not in h.amounts:
            p.amount_cents = h.amount_cents
    if p.intent in _LAUNCH:
        p.occurred_on = h.occurred_on or p.occurred_on or h.weekday_on
        p.installments = h.installments or p.installments
        many = (p.installments or 1) > 1
        if p.intent != "lancar_receita":
            p.intent = "lancar_parcelado" if many else "lancar_despesa"
    return p


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
    return ParsedIntent.of(  # confiança 0.5: sem IA, pergunta "Posso lançar?" antes de gravar
        intent, amount_cents=h.amount_cents, description=description, confidence=0.5,
        occurred_on=h.occurred_on or h.weekday_on, installments=h.installments,
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
            .order_by(Space.created_at, Space.id)  # v1: um espaço familiar por pessoa
            .limit(1)
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
    descartado e ela segue como mensagem nova). Quem vai gravar consome o estado antes
    (`take`): se outra resposta já o consumiu, esta recebe ALREADY_HANDLED."""
    state = await get_state(t.session, t.user_id, t.channel, t.now)
    if state is None or state.kind == "reminder":  # contexto do "paguei", não é pergunta
        return None
    kind, data, reply = state.kind, dict(state.data), answer(text)

    async def take() -> bool:
        return await clear_state(t.session, t.user_id, t.channel)

    async def drop() -> None:  # rascunho abandonado: some o estado e a imagem do comprovante
        await take()
        await discard_draft_attachment(t.session, data)

    if reply == "cancelar":
        await drop()
        return "Ok, cancelei."
    if kind == "correct":
        fields = edit.parse_correction(text, t.today)
        if not await take():
            return ALREADY_HANDLED
        return await edit.apply_correction(t, fields, data.get("tx_id")) if fields else None
    if kind == "delete":  # só um "sim" explícito apaga; "não" cancela; outra coisa é mensagem nova
        if not await take():
            return ALREADY_HANDLED
        if reply == "sim":
            return await edit.confirm_delete(t, UUID(data["tx_id"]))
        return "Ok, não apaguei." if reply == "nao" else None
    try:
        d = Draft.model_validate(data["draft"])
    except (KeyError, ValueError):  # estado velho/malformado não pode travar a conversa
        await drop()
        return None
    if kind == "amount":
        amount = parse_bare_amount(text)
        if amount is None:
            if ZERO_OR_NEG.fullmatch(text.strip()):  # parece valor, mas é zero/negativo
                return ZERO + " Quanto foi?"
            await drop()
            return None
        d.p.amount_cents = amount
    elif kind == "receipt":
        if reply == "nao":
            await drop()
            return "Ok, não lancei."
        out = await receipt.step(t, d, text, reply)
        if out is not receipt.GO:
            if out is None:
                await drop()
            return str(out) if out is not None else None
    elif kind == "confirm":
        if reply != "sim":
            await drop()
            return "Ok, não lancei." if reply == "nao" else None
        d.confirmed = True
    else:  # payment | pick_bill
        picked = pick_option(d.options, text)
        if picked is None:
            if re.fullmatch(r"\d{1,2}", text.strip()):
                return "Responda com um dos números da lista."
            await drop()
            return None
        d.options = []
        if kind == "pick_bill":
            d.bill_id = picked.id
        else:
            d.payment = picked
    if not await take():
        return ALREADY_HANDLED
    return await run_draft(t, d)


async def interpret(
    t: Turn, text: str, h: Hints, space_id: UUID
) -> tuple[ParsedIntent | None, str | None]:
    """Atalho sem LLM; senão LLM + determinístico; se o LLM falhar, o fallback simples."""
    shortcut = try_shortcut(re.sub(r"#\w+", " ", text))  # "#pessoal gastos" também é atalho
    if shortcut is not None:
        return shortcut, None
    if await over_budget(t.session, space_id):
        return fallback_launch(text, h), OVER_BUDGET
    try:
        if t.parser is None:
            raise RuntimeError("no parser configured")
        ctx = await t.context(space_id)
        timeout = get_settings().AI_TIMEOUT_S + 5
        parsed = await asyncio.wait_for(t.parser.parse(text, ctx), timeout)
        model_amount = parsed.amount_cents
        p = merge_hints(parsed, h)
        warn = None
        if p.intent in _LAUNCH and model_amount and p.amount_cents != model_amount:
            if not h.installments:
                warn = f"⚠️ Usei {format_brl(p.amount_cents or 0)}, o valor que você digitou."
        return p, warn
    except HTTPException:
        raise  # isolamento: não é falha da IA
    except Exception as e:
        log.warning("intent parser failed (%s); using the plain fallback", type(e).__name__)
        return fallback_launch(text, h), AI_DOWN


async def fresh(t: Turn, text: str) -> str:
    on = digest_toggle(text)
    if on is not None:
        t.intent = "ajuda"  # ponytail: sem intent própria; só o log do turno
        await t.session.execute(update(User).where(User.id == t.user_id).values(weekly_digest=on))
        await t.session.commit()
        return DIGEST_ON if on else DIGEST_OFF
    h = extract_hints(text, t.today)
    if h.bad_date:
        return BAD_DATE
    space_id, error = await target_space(t, h)
    if space_id is None:
        return error or NOT_UNDERSTOOD
    p, warn = await interpret(t, text, h, space_id)
    if p is None:
        return NOT_UNDERSTOOD
    t.intent = p.intent
    if p.confidence < launch.CONFIDENCE_MIN and p.intent in _WRITES:
        return NOT_UNDERSTOOD  # (lancar_* pergunta "Posso lançar?" em launch.run)
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
            return await pay.start(t, p, text)
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
    if await already_done(t):  # reentrega depois de gravar: nunca grava duas vezes
        return ALREADY
    return await resume(t, text) or await fresh(t, text)


async def handle(session: AsyncSession, ctx: dict[str, Any], row: InboundMessage) -> str | None:
    user = await find_user_by_link(session, row.channel, row.external_user_id)
    if user is None:
        return await unlinked(session, row.channel, row.external_user_id, row.text or "")
    n = await incr_ttl(f"msgrate:{user.id}", 3600)
    if n > get_settings().MSG_RATE_PER_HOUR:  # sem LLM; avisa só 1x
        row.user_id = user.id
        return RATE_LIMITED if n == get_settings().MSG_RATE_PER_HOUR + 1 else None
    row.user_id = user.id
    await session.commit()  # id durável: um rollback adiante não pode deixar a linha sem dono
    t = Turn(
        session=session, user_id=user.id, tz=user.tz, default_space_id=user.default_space_id,
        channel=row.channel, message_id=row.external_message_id, now=row.received_at,
        today=to_local_date(row.received_at, user.tz), parser=ctx.get("parser"),
    )  # fmt: skip
    prefix, text = "", (row.text or "").strip()
    if row.media_kind == "image":  # a legenda só serve para #pessoal/#familia
        h = extract_hints(text, t.today)
        space_id, error = await target_space(t, h)
        if space_id is None:
            return error or NOT_UNDERSTOOD
        if await over_budget(session, space_id):
            return OVER_BUDGET_MEDIA
        return await receipt.start(t, row, ctx.get("receipt_reader"), space_id, h.private)
    if row.media_kind == "audio":
        heard, failure = await transcribe(t, row, ctx.get("transcriber"))
        if heard is None:
            return failure
        text = heard
        prefix = f'🎙️ "{shorten(text)}"\n'
    if not text:
        return None
    reply = await converse(t, text)
    row.result = {"intent": t.intent}
    return prefix + reply


async def transcribe(
    t: Turn, row: InboundMessage, transcriber: Any
) -> tuple[str | None, str | None]:
    """Áudio -> (texto, None) ou (None, resposta de falha). O texto nunca é logado."""
    space_id, _ = await target_space(t, extract_hints("", t.today))
    if space_id is not None and await over_budget(t.session, space_id, stt=True):
        return None, OVER_BUDGET_MEDIA
    try:
        data, mime = await get_adapter(row.channel).download_media(row.media_ref or "", MAX_BYTES)
        heard = await transcriber.transcribe(data, mime)
    except MediaTooLarge:
        return None, TOO_BIG
    except Exception as e:
        log.warning("audio failed (%s)", type(e).__name__)
        return None, AUDIO_FAIL
    if not heard.text:
        return None, AUDIO_FAIL
    if space_id is not None:
        await record_ai_usage(space_id, "stt", seconds=heard.duration_s)
    return str(heard.text), None


def shorten(text: str, limit: int = 120) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def _where(e: BaseException) -> str:
    """Tipo e pilha, sem a mensagem da exceção (pode conter o texto do usuário)."""
    return type(e).__name__ + "\n" + "".join(traceback.format_tb(e.__traceback__))


async def handle_inbound(ctx: dict[str, Any], inbound_id: UUID) -> None:
    """Uma mensagem por vez por (canal, remetente): o ARQ roda jobs em paralelo, e "gastei 45" +
    "1" não podem se atropelar. O lock fica numa conexão própria (os commits no meio do turno
    devolvem a da sessão ao pool, e lock de sessão é por conexão).
    ponytail: sem fila de chegada garantida (quem pega o lock primeiro roda primeiro)."""
    async with SessionLocal() as s0:
        who = (
            await s0.execute(
                select(InboundMessage.channel, InboundMessage.external_user_id).where(
                    InboundMessage.id == inbound_id
                )
            )
        ).first()
    if who is None:
        return
    key = f"{who[0]}:{who[1]}"
    async with engine.connect() as lock:
        await lock.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": key})
        try:
            await _handle_inbound(ctx, inbound_id)
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
            await lock.rollback()


async def _handle_inbound(ctx: dict[str, Any], inbound_id: UUID) -> None:
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
        except IntegrityError as e:
            await session.rollback()
            if "uq_transactions_origin_source_message" not in str(e):
                log.error("process_inbound failed: %s", _where(e))
                reply, status = FAILED, "failed"
            else:  # corrida: outro worker gravou esta mesma mensagem
                reply = ALREADY
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
        row.status, row.text = status, None  # LGPD: terminal descarta o texto
        await session.commit()
        if reply:
            try:
                await get_adapter(channel).send_text(external_user_id, reply)
            except Exception as e:
                log.warning("send_text failed (%s)", type(e).__name__)

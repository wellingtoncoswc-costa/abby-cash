from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session, rate_limit
from app.channels.evolution import EvolutionClient, InstanceNotFound
from app.channels.registry import evolution_adapter
from app.channels.telegram import ChannelError
from app.core.config import get_settings
from app.domain.audit import audit
from app.domain.users.service import create_signup_invite

router = APIRouter(prefix="/admin", tags=["admin"])


class SignupInviteOut(BaseModel):
    code: str
    expires_at: datetime


@router.post("/signup-invites", status_code=201, response_model=SignupInviteOut)
async def signup_invite(user: CurrentUser, session: Session) -> SignupInviteOut:
    """O código só aparece nesta resposta (7 dias de validade)."""
    if not user.is_admin:
        raise HTTPException(403, "admin_only")
    await rate_limit(f"signup_invite:{user.id}", 20)
    inv = await create_signup_invite(session, created_by=user.id)
    audit(session, user.id, "signup_invite.create", "signup_invite", inv.id)
    await session.commit()
    return SignupInviteOut(code=inv.code, expires_at=inv.expires_at)


class WhatsappOut(BaseModel):
    state: str  # open | connecting | close | none
    qr: str | None = None  # data URL do QR; só quando há o que escanear


def _evolution() -> EvolutionClient:
    s = get_settings()
    if not (s.EVOLUTION_URL and s.EVOLUTION_API_KEY and s.EVOLUTION_INSTANCE):
        raise HTTPException(503, "whatsapp_not_configured")
    return evolution_adapter().client


async def _state(client: EvolutionClient) -> str:
    try:
        return await client.connection_state()
    except InstanceNotFound:
        return "none"
    except ChannelError:
        raise HTTPException(502, "whatsapp_unavailable") from None


@router.get("/whatsapp", response_model=WhatsappOut)
async def whatsapp_status(user: CurrentUser) -> WhatsappOut:
    if not user.is_admin:
        raise HTTPException(403, "admin_only")
    return WhatsappOut(state=await _state(_evolution()))


@router.post("/whatsapp/qr", response_model=WhatsappOut)
async def whatsapp_qr(user: CurrentUser, session: Session) -> WhatsappOut:
    """Cria a instância se faltar, registra o webhook e devolve o QR para parear o chip."""
    if not user.is_admin:
        raise HTTPException(403, "admin_only")
    await rate_limit(f"whatsapp_qr:{user.id}", 30)
    client, s = _evolution(), get_settings()
    state = await _state(client)
    if state == "open":
        return WhatsappOut(state="open")
    try:
        if state == "none":
            qr = await client.create_instance()
            await client.set_webhook(
                s.EVOLUTION_WEBHOOK_URL
                or f"{s.PUBLIC_BASE_URL.rstrip('/')}/webhooks/whatsapp_evolution",
                s.EVOLUTION_WEBHOOK_SECRET,
            )
        else:
            qr = await client.connect_qr()
    except ChannelError:
        raise HTTPException(502, "whatsapp_unavailable") from None
    audit(session, user.id, "whatsapp.qr", "channel", user.id)
    await session.commit()
    return WhatsappOut(state="connecting", qr=qr)


@router.post("/whatsapp/logout", response_model=WhatsappOut)
async def whatsapp_logout(user: CurrentUser, session: Session) -> WhatsappOut:
    if not user.is_admin:
        raise HTTPException(403, "admin_only")
    client = _evolution()
    try:
        await client.logout()
    except InstanceNotFound:
        pass
    except ChannelError:
        raise HTTPException(502, "whatsapp_unavailable") from None
    audit(session, user.id, "whatsapp.logout", "channel", user.id)
    await session.commit()
    return WhatsappOut(state=await _state(client))

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import MAX_FAILS, _hit
from app.api.deps import CurrentUser, Session
from app.channels.registry import telegram_adapter
from app.channels.telegram import ChannelError
from app.core.config import get_settings
from app.domain.channels.linking import CODE_TTL_S, create_link_code, unlink
from app.domain.channels.models import ChannelLink

router = APIRouter(prefix="/channels", tags=["channels"])


Channel = Literal["telegram"]  # M4 acrescenta whatsapp_evolution


class LinkCodeIn(BaseModel):
    channel: Channel


async def _deep_link(code: str) -> str | None:
    """t.me/<bot>?start=<código>; o @ do bot vem do env ou de getMe, nunca fixo no código."""
    try:
        name = get_settings().TELEGRAM_BOT_USERNAME or await telegram_adapter().bot_username()
    except ChannelError:
        return None  # sem token/rede: o painel mostra só o código
    return f"https://t.me/{name}?start={code}"


@router.post("/link-code")
async def link_code(body: LinkCodeIn, user: CurrentUser) -> dict[str, object]:
    await _hit(f"link_code:{user.id}", MAX_FAILS)  # 5 códigos por janela
    code = await create_link_code(user.id, body.channel)
    return {
        "code": code,
        "expires_in_s": CODE_TTL_S,
        "deep_link": await _deep_link(code) if body.channel == "telegram" else None,
    }


@router.get("")
async def list_links(user: CurrentUser, session: Session) -> list[dict[str, object]]:
    links = await session.scalars(select(ChannelLink).where(ChannelLink.user_id == user.id))
    return [{"channel": k.channel, "verified_at": k.verified_at} for k in links]


@router.delete("/{channel}", status_code=204)
async def delete_link(channel: Channel, user: CurrentUser, session: Session) -> None:
    await unlink(session, user.id, channel)

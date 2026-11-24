import hmac
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from starlette.requests import Request

from app.channels.base import InboundMessage, MediaTooLarge
from app.core.config import get_settings

# httpx loga a URL completa em INFO, e a URL da Bot API contém o token
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

API = "https://api.telegram.org"
_MIME = {
    ".oga": "audio/ogg", ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
}  # fmt: skip


class ChannelError(Exception):
    """Falha de envio/recebimento. A mensagem nunca carrega a URL (que contém o token)."""


class TelegramAdapter:
    name = "telegram"

    def __init__(self, token: str, secret: str, client: httpx.AsyncClient | None = None) -> None:
        self._token, self._secret = token, secret
        # read > 30 s do long polling do getUpdates
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=5.0))
        self._username: str | None = None

    def verify(self, request: Request) -> bool:
        got = request.headers.get("x-telegram-bot-api-secret-token", "")
        # sem segredo configurado nada passa; bytes: compare_digest recusa str não ASCII
        return bool(self._secret) and hmac.compare_digest(got.encode(), self._secret.encode())

    def parse_update(self, update: Any) -> InboundMessage | None:
        """Update da Bot API -> mensagem. Só conversa 1:1, de gente, com texto ou mídia.

        Payload malformado levanta `ValueError` (webhook -> 400; polling pula o update)."""
        try:
            return self._parse(update)
        except (
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
            ValueError,
            OverflowError,
            OSError,
        ):
            raise ValueError("malformed telegram update") from None

    def _parse(self, update: Any) -> InboundMessage | None:
        if not isinstance(update, dict):
            raise ValueError
        msg = update.get("message")
        if not msg or msg.get("chat", {}).get("type") != "private":
            return None
        if (msg.get("from") or {}).get("is_bot"):
            return None
        chat_id = msg["chat"]["id"]
        media_kind: Any = None
        media_ref: str | None = None
        if "voice" in msg or "audio" in msg:
            media_kind, media_ref = "audio", (msg.get("voice") or msg["audio"])["file_id"]
        elif "photo" in msg:
            media_kind, media_ref = "image", msg["photo"][-1]["file_id"]  # a maior resolução
        text = msg.get("text") or msg.get("caption")
        if text is None and media_kind is None:
            return None
        return InboundMessage(
            channel=self.name,
            external_message_id=f"{chat_id}:{msg['message_id']}",
            external_user_id=str(chat_id),
            text=text,
            media_kind=media_kind,
            media_ref=media_ref,
            received_at=datetime.fromtimestamp(msg["date"], UTC),
        )

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        parsed = self.parse_update(await request.json())
        return [parsed] if parsed else []

    async def _call(self, method: str, **payload: Any) -> Any:
        try:
            r = await self._client.post(f"{API}/bot{self._token}/{method}", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ChannelError(f"telegram {method} failed ({type(e).__name__})") from None
        try:
            return r.json()["result"]
        except (KeyError, ValueError, TypeError):
            raise ChannelError(f"telegram {method} bad response") from None

    async def send_text(self, external_user_id: str, text: str) -> None:
        await self._call("sendMessage", chat_id=int(external_user_id), text=text[:4096])

    async def download_media(self, media_ref: str, max_bytes: int) -> tuple[bytes, str]:
        info = await self._call("getFile", file_id=media_ref)
        if int(info.get("file_size") or 0) > max_bytes:  # antes de baixar
            raise MediaTooLarge
        path = info["file_path"]
        try:
            r = await self._client.get(f"{API}/file/bot{self._token}/{path}")
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ChannelError(f"telegram download failed ({type(e).__name__})") from None
        if len(r.content) > max_bytes:
            raise MediaTooLarge
        mime = _MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        return r.content, mime

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return list(await self._call("getUpdates", **payload))

    async def set_webhook(self, url: str) -> None:
        await self._call(
            "setWebhook", url=url, secret_token=self._secret, allowed_updates=["message"]
        )

    async def delete_webhook(self) -> None:
        await self._call("deleteWebhook")

    async def bot_username(self) -> str:
        """@ do bot: TELEGRAM_BOT_USERNAME se houver; senão getMe (uma vez por processo)."""
        configured = get_settings().TELEGRAM_BOT_USERNAME
        if configured:
            return configured
        if self._username is None:
            self._username = str((await self._call("getMe"))["username"])
        return self._username

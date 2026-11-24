import base64
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from starlette.requests import Request

from app.channels.base import InboundMessage
from app.channels.telegram import ChannelError

log = logging.getLogger(__name__)

# a URL e o header carregam a chave: nada de log de requisições do httpx
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

_USER_JID = "@s.whatsapp.net"  # só 1:1; fora: @g.us, status@broadcast, @newsletter
_WRAPPERS = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "documentWithCaptionMessage",
)


class EvolutionClient:
    """API REST da Evolution v2. A chave só vai no header `apikey`; erros nunca levam URL/chave."""

    def __init__(
        self, url: str, api_key: str, instance: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._url, self._key, self._instance = url.rstrip("/"), api_key, instance
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

    async def _call(self, method: str, path: str, **payload: Any) -> Any:
        try:
            r = await self._client.request(
                method, f"{self._url}/{path}/{self._instance}",
                headers={"apikey": self._key}, json=payload or None,
            )  # fmt: skip
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ChannelError(f"evolution {path} failed ({type(e).__name__})") from None

    async def send_text(self, number: str, text: str) -> None:
        await self._call("POST", "message/sendText", number=number, text=text[:4096])

    async def connection_state(self) -> str:
        data = await self._call("GET", "instance/connectionState")
        try:
            return str(data["instance"]["state"])
        except (KeyError, TypeError):
            raise ChannelError("evolution connectionState bad response") from None

    async def set_webhook(self, url: str, secret: str) -> None:
        await self._call(
            "POST", "webhook/set",
            webhook={
                "enabled": True, "url": url, "byEvents": False, "base64": False,
                "events": ["MESSAGES_UPSERT"], "headers": {"x-webhook-secret": secret},
            },
        )  # fmt: skip

    async def get_base64(self, message_id: str) -> tuple[bytes, str]:
        data = await self._call(
            "POST", "chat/getBase64FromMediaMessage", message={"key": {"id": message_id}}
        )
        try:
            mime = str(data["mimetype"]).split(";")[0].strip()
            return base64.b64decode(data["base64"]), mime
        except (KeyError, TypeError, ValueError):
            raise ChannelError("evolution media bad response") from None


class EvolutionAdapter:
    name = "whatsapp_evolution"

    def __init__(self, client: EvolutionClient, secret: str) -> None:
        self.client, self._secret = client, secret

    def verify(self, request: Request) -> bool:
        got = request.headers.get("x-webhook-secret", "")
        # sem segredo configurado nada passa; bytes: compare_digest recusa str não ASCII
        return bool(self._secret) and hmac.compare_digest(got.encode(), self._secret.encode())

    def parse_event(self, body: Any) -> InboundMessage | None:
        """Evento da Evolution -> mensagem. Só `messages.upsert` 1:1 de terceiros; o resto é
        ignorado. Payload fora do formato levanta `ValueError` (webhook -> 400)."""
        try:
            return self._parse(body)
        except (
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
            ValueError,
            OverflowError,
            OSError,
        ):
            raise ValueError("malformed evolution event") from None

    def _parse(self, body: Any) -> InboundMessage | None:
        if not isinstance(body, dict):
            raise ValueError
        if str(body.get("event", "")).lower().replace("_", ".") != "messages.upsert":
            return None
        data = body["data"]
        key = data["key"]
        jid = key["remoteJid"]
        if jid.endswith("@lid"):  # número real em campos alternativos (Evolution >= 2.3)
            jid = key.get("remoteJidAlt") or key.get("senderPn") or data.get("senderPn") or jid
        if key.get("fromMe") or not jid.endswith(_USER_JID) or not jid[: -len(_USER_JID)].isdigit():
            return None
        msg = data.get("message") or {}
        for _ in range(3):  # desembrulha mensagens temporárias / visualização única / doc + legenda
            inner = next((msg[w].get("message") for w in _WRAPPERS if w in msg), None)
            if not isinstance(inner, dict):
                break
            msg = inner
        text = msg.get("conversation") or (msg.get("extendedTextMessage") or {}).get("text")
        media_kind: Any = None
        if "audioMessage" in msg:
            media_kind = "audio"
        elif "imageMessage" in msg:
            media_kind, text = "image", text or msg["imageMessage"].get("caption")
        if not text and media_kind is None:
            # só o tipo do evento: nunca conteúdo nem número
            log.info("evolution unsupported message type=%s", str(data.get("messageType"))[:40])
            return None
        mid = key["id"]
        return InboundMessage(
            channel=self.name,
            external_message_id=str(mid),
            external_user_id=jid[: -len(_USER_JID)],
            text=text or None,
            media_kind=media_kind,
            media_ref=str(mid) if media_kind else None,
            received_at=datetime.fromtimestamp(int(data["messageTimestamp"]), UTC),
        )

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        parsed = self.parse_event(await request.json())
        return [parsed] if parsed else []

    async def send_text(self, external_user_id: str, text: str) -> None:
        await self.client.send_text(external_user_id, text)

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        return await self.client.get_base64(media_ref)  # M6 usa

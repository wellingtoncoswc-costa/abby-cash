from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from starlette.requests import Request


@dataclass
class InboundMessage:
    channel: str  # "telegram" | "whatsapp_evolution" | "whatsapp_cloud"
    external_message_id: str  # único por canal: base da idempotência
    external_user_id: str  # chat_id / telefone E.164
    text: str | None
    media_kind: Literal["audio", "image"] | None
    media_ref: str | None
    received_at: datetime


class ChannelAdapter(Protocol):
    name: str

    async def parse_webhook(self, request: Request) -> list[InboundMessage]: ...

    def verify(self, request: Request) -> bool: ...

    async def send_text(self, external_user_id: str, text: str) -> None: ...

    async def download_media(self, media_ref: str) -> tuple[bytes, str]: ...  # (bytes, mime)

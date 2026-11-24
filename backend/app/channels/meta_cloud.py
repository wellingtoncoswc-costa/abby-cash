from starlette.requests import Request

from app.channels.base import InboundMessage


class MetaCloudAdapter:
    """Esqueleto da API oficial do WhatsApp (fase de venda). Nada é registrado em `registry`."""

    name = "whatsapp_cloud"

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")

    def verify(self, request: Request) -> bool:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")

    async def send_text(self, external_user_id: str, text: str) -> None:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        raise NotImplementedError("WhatsApp Cloud API: fase de venda")

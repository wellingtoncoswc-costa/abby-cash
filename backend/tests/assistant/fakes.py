from starlette.requests import Request

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent
from app.channels.base import InboundMessage


class FakeAdapter:
    """Canal falso: guarda o que seria enviado ao usuário."""

    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (external_user_id, texto)

    def verify(self, request: Request) -> bool:
        return True

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        return []

    async def send_text(self, external_user_id: str, text: str) -> None:
        self.sent.append((external_user_id, text))

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        return b"", "application/octet-stream"


class FakeParser:
    """Interpretador falso: devolve os resultados na ordem (ou levanta, se for uma exceção)."""

    def __init__(self, *results: "ParsedIntent | Exception") -> None:
        self._results = list(results)
        self.calls: list[tuple[str, SpaceContext]] = []

    async def parse(self, text: str, ctx: SpaceContext) -> ParsedIntent:
        self.calls.append((text, ctx))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

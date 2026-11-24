from typing import Any

from pydantic import PrivateAttr
from starlette.requests import Request

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent
from app.channels.base import InboundMessage
from app.channels.telegram import TelegramAdapter
from app.core.text import fold


class FakeAdapter:
    """Canal falso: guarda o que seria enviado ao usuário."""

    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (external_user_id, texto)
        self.downloads: list[str] = []
        self.media, self.media_mime = b"", "application/octet-stream"

    def verify(self, request: Request) -> bool:
        return True

    async def parse_webhook(self, request: Request) -> list[InboundMessage]:
        parsed = TelegramAdapter("T", "s").parse_update(await request.json())
        return [parsed] if parsed else []

    async def send_text(self, external_user_id: str, text: str) -> None:
        self.sent.append((external_user_id, text))

    async def download_media(self, media_ref: str, max_bytes: int) -> tuple[bytes, str]:
        self.downloads.append(media_ref)
        return self.media, self.media_mime


class FakeIntent(ParsedIntent):
    """ParsedIntent que aceita o NOME da categoria nos testes; o parser falso o converte no nº
    da lista do prompt (como o modelo real faz)."""

    _cat: str | None = PrivateAttr(default=None)


def intent(kind: Any, category_name: str | None = None, **fields: Any) -> FakeIntent:
    out = FakeIntent.of(kind, **fields)
    out._cat = category_name
    return out


def expense(amount: int | None, category_name: str | None = None, **fields: Any) -> FakeIntent:
    return intent("lancar_despesa", category_name, amount_cents=amount, **fields)


class FakeParser:
    """Interpretador falso: devolve os resultados na ordem (ou levanta, se for uma exceção)."""

    def __init__(self, *results: "ParsedIntent | Exception") -> None:
        self._results = list(results)
        self.calls: list[tuple[str, SpaceContext]] = []

    def add(self, *results: "ParsedIntent | Exception") -> None:
        self._results.extend(results)

    async def parse(self, text: str, ctx: SpaceContext) -> ParsedIntent:
        self.calls.append((text, ctx))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        name = getattr(result, "_cat", None)
        if name is not None:
            kind = "income" if result.intent == "lancar_receita" else "expense"
            idx = next(
                i
                for i, c in enumerate(ctx.categories, 1)
                if c.kind == kind and fold(c.name) == fold(name)
            )
            result = result.model_copy(update={"category_index": idx})
        return result


class FakeTranscriber:
    def __init__(self, text: str = "", duration_s: float = 3.5, error: Exception | None = None):
        self.text, self.duration_s, self.error = text, duration_s, error
        self.calls: list[tuple[int, str]] = []

    async def transcribe(self, audio: bytes, mime: str):
        from app.ai.stt import Transcript

        self.calls.append((len(audio), mime))
        if self.error:
            raise self.error
        return Transcript(self.text, self.duration_s)


class FakeReader:
    def __init__(self, *results: Any) -> None:
        self.results = list(results)

    async def read(self, image: bytes, mime: str, space_id: Any = None):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

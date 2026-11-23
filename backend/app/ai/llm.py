from typing import Protocol

from app.assistant.context import SpaceContext
from app.assistant.intents import ParsedIntent


class IntentParser(Protocol):
    """Interpreta uma mensagem de texto. Levanta qualquer exceção se não conseguir: quem chama
    degrada para o atalho determinístico (spec 9)."""

    async def parse(self, text: str, ctx: SpaceContext) -> ParsedIntent: ...

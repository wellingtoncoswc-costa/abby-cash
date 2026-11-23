from typing import Any
from uuid import UUID

from app.assistant.processor import handle_inbound


async def process_inbound(ctx: dict[str, Any], inbound_id: str) -> None:
    """Job do ARQ: interpreta e responde uma mensagem recebida (id vem como texto da fila)."""
    await handle_inbound(ctx, UUID(inbound_id))

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.context import SpaceContext, load_space_context
from app.assistant.intents import ParsedIntent


class Pay(BaseModel):
    """Uma opção/escolha: conta, cartão ou conta a pagar (rótulo já pronto para mostrar)."""

    type: Literal["account", "card", "bill"]
    id: UUID
    label: str


class Draft(BaseModel):
    """Ação em andamento que precisou perguntar algo; vai inteira para `conversation_state`."""

    action: Literal["launch", "pay", "aporte"]
    p: ParsedIntent
    space_id: UUID
    payment: Pay | None = None
    bill_id: UUID | None = None
    options: list[Pay] = []
    warn: str | None = None
    confirmed: bool = False
    private: bool = False


@dataclass
class Turn:
    """Tudo que um fluxo precisa de uma mensagem. Só escalares do usuário: um rollback expira
    os objetos ORM, e ler atributo expirado em sessão async dá erro."""

    session: AsyncSession
    user_id: UUID
    tz: str
    default_space_id: UUID | None
    channel: str
    message_id: str  # id externo: vira `source_message_id` dos lançamentos
    now: datetime
    today: date
    parser: Any  # IntentParser (ou None se o worker não configurou)
    intent: str | None = None
    _contexts: dict[UUID, SpaceContext] = field(default_factory=dict)

    async def context(self, space_id: UUID) -> SpaceContext:
        if space_id not in self._contexts:
            self._contexts[space_id] = await load_space_context(
                self.session, user_id=self.user_id, space_id=space_id, today=self.today, tz=self.tz
            )
        return self._contexts[space_id]

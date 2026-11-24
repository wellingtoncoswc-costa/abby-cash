from typing import cast

from app.channels.base import ChannelAdapter
from app.channels.evolution import EvolutionAdapter, EvolutionClient
from app.channels.telegram import TelegramAdapter
from app.core.config import get_settings

_adapters: dict[str, ChannelAdapter] = {}


def get_adapter(channel: str) -> ChannelAdapter:
    """Adaptador do canal; `KeyError` se o canal não existe/ainda não foi habilitado."""
    if channel not in _adapters:
        s = get_settings()
        if channel == "telegram":
            _adapters[channel] = TelegramAdapter(s.TELEGRAM_BOT_TOKEN, s.TELEGRAM_WEBHOOK_SECRET)
        elif channel == "whatsapp_evolution":
            client = EvolutionClient(s.EVOLUTION_URL, s.EVOLUTION_API_KEY, s.EVOLUTION_INSTANCE)
            _adapters[channel] = EvolutionAdapter(client, s.EVOLUTION_WEBHOOK_SECRET)
        else:
            raise KeyError(channel)
    return _adapters[channel]


def telegram_adapter() -> TelegramAdapter:
    return cast(TelegramAdapter, get_adapter("telegram"))


def evolution_adapter() -> EvolutionAdapter:
    return cast(EvolutionAdapter, get_adapter("whatsapp_evolution"))

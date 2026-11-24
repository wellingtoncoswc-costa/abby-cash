from typing import cast

from app.channels.base import ChannelAdapter
from app.channels.telegram import TelegramAdapter
from app.core.config import get_settings

_adapters: dict[str, ChannelAdapter] = {}


def get_adapter(channel: str) -> ChannelAdapter:
    """Adaptador do canal; `KeyError` se o canal não existe/ainda não foi habilitado."""
    if channel not in _adapters:
        if channel != "telegram":  # M4 acrescenta whatsapp_evolution
            raise KeyError(channel)
        s = get_settings()
        _adapters[channel] = TelegramAdapter(s.TELEGRAM_BOT_TOKEN, s.TELEGRAM_WEBHOOK_SECRET)
    return _adapters[channel]


def telegram_adapter() -> TelegramAdapter:
    return cast(TelegramAdapter, get_adapter("telegram"))

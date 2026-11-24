from types import SimpleNamespace

import pytest

from app import cli
from app.core import config


@pytest.mark.parametrize(
    ("token", "secret"),
    [("", "ok"), ("T", ""), ("T", "has space"), ("T", "ação"), ("T", "x" * 257)],
)
async def test_set_webhook_rejects_bad_config(monkeypatch, token, secret):
    s = SimpleNamespace(
        TELEGRAM_BOT_TOKEN=token, TELEGRAM_WEBHOOK_SECRET=secret, PUBLIC_BASE_URL="https://x"
    )
    monkeypatch.setattr(config, "get_settings", lambda: s)
    with pytest.raises(SystemExit, match="TELEGRAM_"):
        await cli._set_webhook(None)


@pytest.mark.parametrize(
    ("url", "secret"),
    [("", "x" * 20), ("http://e", ""), ("http://e", "short"), ("http://e", "a b" * 8)],
)
async def test_evolution_set_webhook_rejects_bad_config(monkeypatch, url, secret):
    s = SimpleNamespace(
        EVOLUTION_URL=url, EVOLUTION_API_KEY="K", EVOLUTION_INSTANCE="abby",
        EVOLUTION_WEBHOOK_SECRET=secret, PUBLIC_BASE_URL="https://x",
    )  # fmt: skip
    monkeypatch.setattr(config, "get_settings", lambda: s)
    with pytest.raises(SystemExit, match="EVOLUTION_"):
        await cli._evolution_set_webhook(None)

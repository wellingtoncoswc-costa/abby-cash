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

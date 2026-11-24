from pathlib import Path

import pytest

from app.core.config import _ENV_FILE, Settings


def test_env_file_is_repo_root_absolute():
    assert _ENV_FILE.is_absolute() and _ENV_FILE.name == ".env"
    assert (_ENV_FILE.parent / "backend" / "app").is_dir()


def test_settings_reads_given_env_file(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text("STT_MODEL=tiny\n")
    assert Settings(_env_file=f).STT_MODEL == "tiny"  # type: ignore[call-arg]
    assert Settings(_env_file=tmp_path / "missing").STT_MODEL  # ausente é tolerado  # type: ignore[call-arg]


def test_m3_settings_defaults(tmp_path: Path):
    s = Settings(_env_file=tmp_path / "missing")  # type: ignore[call-arg]
    assert s.TELEGRAM_BOT_USERNAME == ""
    assert s.AI_TIMEOUT_S == 10.0


def _prod(tmp_path: Path, **kw) -> Settings:
    base = {
        "ENV": "prod", "JWT_SECRET": "j" * 32, "TOTP_ENC_KEY": "k",
        "TELEGRAM_WEBHOOK_SECRET": "t" * 20,
    }  # fmt: skip
    return Settings(_env_file=tmp_path / "missing", **{**base, **kw})  # type: ignore[call-arg]


def test_prod_rejects_weak_webhook_secrets(tmp_path: Path):
    _prod(tmp_path)  # ok
    for bad in ("", "short", "change-me-change-me-change"):
        with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET"):
            _prod(tmp_path, TELEGRAM_WEBHOOK_SECRET=bad)
    evo = {"EVOLUTION_URL": "http://evolution:8080"}
    with pytest.raises(ValueError, match="EVOLUTION_WEBHOOK_SECRET"):
        _prod(tmp_path, **evo, EVOLUTION_API_KEY="a" * 20)
    with pytest.raises(ValueError, match="EVOLUTION_API_KEY"):
        _prod(
            tmp_path,
            **evo,
            EVOLUTION_WEBHOOK_SECRET="w" * 20,
            EVOLUTION_API_KEY="change-me-evolution-key",
        )
    _prod(tmp_path, **evo, EVOLUTION_WEBHOOK_SECRET="w" * 20, EVOLUTION_API_KEY="a" * 20)

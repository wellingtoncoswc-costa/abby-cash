from pathlib import Path

from app.core.config import _ENV_FILE, Settings


def test_env_file_is_repo_root_absolute():
    assert _ENV_FILE.is_absolute() and _ENV_FILE.name == ".env"
    assert (_ENV_FILE.parent / "backend" / "app").is_dir()


def test_settings_reads_given_env_file(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text("STT_MODEL=tiny\n")
    assert Settings(_env_file=f).STT_MODEL == "tiny"  # type: ignore[call-arg]
    assert Settings(_env_file=tmp_path / "missing").STT_MODEL  # ausente é tolerado  # type: ignore[call-arg]

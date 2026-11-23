from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"  # raiz do repo; ausente é tolerado


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    ENV: str = "dev"
    DATABASE_URL: str = "postgresql+asyncpg://abby:abby@localhost:5432/abby"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "dev-only-change-me"
    AI_MODEL: str = "claude-opus-5-5"
    ANTHROPIC_API_KEY: str = ""
    STT_URL: str = "http://stt:8000"
    STT_MODEL: str = "small"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    EVOLUTION_URL: str = ""
    EVOLUTION_API_KEY: str = ""
    EVOLUTION_INSTANCE: str = ""
    EVOLUTION_WEBHOOK_SECRET: str = ""
    STORAGE_DIR: str = "./storage"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    DEFAULT_TZ: str = "America/Sao_Paulo"

    @model_validator(mode="after")
    def _reject_default_secret_in_prod(self) -> "Settings":
        if self.ENV == "prod" and self.JWT_SECRET in {"dev-only-change-me", "change-me", ""}:
            raise ValueError("JWT_SECRET must be set in prod")
        if self.ENV == "prod" and len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET must be at least 32 chars in prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

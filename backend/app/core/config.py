from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

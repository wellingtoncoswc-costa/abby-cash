from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"  # raiz do repo; ausente é tolerado


def _need_secret(name: str, value: str) -> None:
    if len(value) < 16 or "change-me" in value:
        raise ValueError(f"{name} must be 16+ chars and not a placeholder in prod")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    ENV: str = "dev"
    DATABASE_URL: str = "postgresql+asyncpg://abby:abby@localhost:5432/abby"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "dev-only-change-me"
    AI_MODEL: str = "gpt-4.1"
    OPENAI_API_KEY: str = ""
    AI_TIMEOUT_S: float = 10.0
    STT_URL: str = "http://stt:8000"
    STT_MODEL: str = "small"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_BOT_USERNAME: str = ""  # opcional: vazio = descobre com getMe
    EVOLUTION_URL: str = ""
    EVOLUTION_API_KEY: str = ""
    EVOLUTION_INSTANCE: str = ""
    EVOLUTION_WEBHOOK_URL: str = (
        ""  # opcional: URL interna (prod: http://api:8000/webhooks/whatsapp_evolution)
    )
    EVOLUTION_WEBHOOK_SECRET: str = ""
    STORAGE_DIR: str = "./storage"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    DEFAULT_TZ: str = "America/Sao_Paulo"
    TOTP_ENC_KEY: str = ""  # chave Fernet (urlsafe base64 de 32 bytes); obrigatória em prod
    TRUSTED_PROXIES: str = ""  # CIDRs separados por vírgula; só deles se aceita X-Forwarded-For
    HSTS: bool = False  # ligar só atrás de TLS
    WEBHOOK_RATE_PER_MIN: int = 600  # teto generoso por IP
    HEARTBEAT_STALE_S: int = 90
    MSG_RATE_PER_HOUR: int = 60  # mensagens por usuário/hora (teto de abuso/custo)
    AI_DAILY_TOKEN_BUDGET: int = 200_000  # tokens de IA por espaço nas últimas 24h
    STT_DAILY_SECONDS: int = 1800  # segundos de áudio por espaço nas últimas 24h

    @model_validator(mode="after")
    def _reject_default_secret_in_prod(self) -> "Settings":
        if self.ENV == "prod" and self.JWT_SECRET in {"dev-only-change-me", "change-me", ""}:
            raise ValueError("JWT_SECRET must be set in prod")
        if self.ENV == "prod" and len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET must be at least 32 chars in prod")
        if self.ENV == "prod" and not self.TOTP_ENC_KEY:
            raise ValueError("TOTP_ENC_KEY must be set in prod")
        if self.ENV == "prod":
            _need_secret("TELEGRAM_WEBHOOK_SECRET", self.TELEGRAM_WEBHOOK_SECRET)
            if self.EVOLUTION_URL:
                _need_secret("EVOLUTION_WEBHOOK_SECRET", self.EVOLUTION_WEBHOOK_SECRET)
                _need_secret("EVOLUTION_API_KEY", self.EVOLUTION_API_KEY)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

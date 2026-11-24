from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

_PREFIX = "enc:"


def encrypt(plain: str) -> str:
    key = get_settings().TOTP_ENC_KEY
    return _PREFIX + Fernet(key).encrypt(plain.encode()).decode() if key else plain


def decrypt(stored: str) -> str:
    """Valor sem prefixo `enc:` é texto puro legado: lido como está e cifrado na próxima escrita."""
    if not stored.startswith(_PREFIX):
        return stored
    try:
        return Fernet(get_settings().TOTP_ENC_KEY).decrypt(stored[len(_PREFIX) :].encode()).decode()
    except (InvalidToken, ValueError):
        raise RuntimeError("TOTP_ENC_KEY does not match the stored secret") from None


class EncryptedStr(TypeDecorator[str]):
    impl = String(255)
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: object) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        return None if value is None else decrypt(value)

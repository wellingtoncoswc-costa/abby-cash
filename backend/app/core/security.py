import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_ph = PasswordHasher()  # Argon2id por padrão


def hash_password(pwd: str) -> str:
    return _ph.hash(pwd)


def verify_password(pwd: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pwd)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: UUID) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=15)
    return jwt.encode({"sub": str(user_id), "exp": exp}, get_settings().JWT_SECRET, "HS256")


def decode_access_token(token: str) -> UUID | None:
    try:
        data = jwt.decode(
            token,
            get_settings().JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
        return UUID(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_opaque_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

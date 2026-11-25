from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.redis import incr_ttl
from app.core.security import decode_access_token
from app.domain.users.models import User

Session = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: Session, authorization: Annotated[str | None, Header()] = None
) -> User:
    scheme, _, token = (authorization or "").partition(" ")
    uid = decode_access_token(token) if scheme.lower() == "bearer" else None
    user = await session.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(401, "invalid_token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def rate_limit(key: str, limit: int, ttl_s: int = 3600) -> None:
    """Mais de `limit` chamadas por janela -> 429."""
    if await incr_ttl(key, ttl_s) > limit:
        raise HTTPException(429, "too_many_requests")

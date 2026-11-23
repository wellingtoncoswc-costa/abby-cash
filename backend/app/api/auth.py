from typing import Annotated

import pyotp
from fastapi import APIRouter, Cookie, HTTPException, Response
from pydantic import BaseModel, EmailStr

from app.api.deps import CurrentUser, Session
from app.core.redis import redis
from app.core.security import create_access_token
from app.domain.users.service import (
    AuthError,
    authenticate,
    issue_refresh,
    register_user,
    rotate_refresh,
)

router = APIRouter(prefix="/auth", tags=["auth"])
MAX_FAILS, FAIL_TTL = 5, 900
REFRESH_MAX_AGE = 30 * 86400


class RegisterIn(BaseModel):
    email: EmailStr
    name: str
    password: str
    invite_code: str


class LoginIn(BaseModel):
    email: str
    password: str
    totp: str | None = None


class CodeIn(BaseModel):
    code: str


def _set_cookie(resp: Response, raw: str) -> None:
    resp.set_cookie(
        "refresh_token", raw, max_age=REFRESH_MAX_AGE, path="/auth",
        httponly=True, secure=True, samesite="lax",
    )  # fmt: skip


@router.post("/register", status_code=201)
async def register(body: RegisterIn, session: Session) -> dict[str, str]:
    try:
        user = await register_user(
            session, email=body.email, name=body.name,
            password=body.password, invite_code=body.invite_code,
        )  # fmt: skip
    except ValueError:
        raise HTTPException(400, "invalid_invite") from None
    return {"id": str(user.id), "email": user.email}


@router.post("/login")
async def login(body: LoginIn, session: Session, resp: Response) -> dict[str, str]:
    key = f"login_fail:{body.email.strip().lower()}"
    if int(await redis.get(key) or 0) >= MAX_FAILS:  # antes de verificar a senha
        raise HTTPException(429, "too_many_attempts")
    try:
        user = await authenticate(session, body.email, body.password, body.totp)
    except AuthError as e:
        if str(e) == "invalid_credentials":
            await redis.incr(key)
            await redis.expire(key, FAIL_TTL)
        raise HTTPException(401, str(e)) from None
    await redis.delete(key)
    _set_cookie(resp, await issue_refresh(session, user.id))
    return {"access_token": create_access_token(user.id)}


@router.post("/refresh")
async def refresh(
    session: Session, resp: Response, refresh_token: Annotated[str | None, Cookie()] = None
) -> dict[str, str]:
    try:
        user, raw = await rotate_refresh(session, refresh_token or "")
    except AuthError:
        raise HTTPException(401, "invalid_refresh") from None
    _set_cookie(resp, raw)
    return {"access_token": create_access_token(user.id)}


@router.post("/2fa/setup")
async def setup_2fa(user: CurrentUser, session: Session) -> dict[str, str]:
    if user.totp_enabled:
        raise HTTPException(409, "totp_already_enabled")
    user.totp_secret = pyotp.random_base32()
    await session.commit()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name="Abby Cash")
    return {"secret": user.totp_secret, "uri": uri}


@router.post("/2fa/verify")
async def verify_2fa(body: CodeIn, user: CurrentUser, session: Session) -> dict[str, bool]:
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise HTTPException(400, "invalid_code")
    user.totp_enabled = True
    await session.commit()
    return {"totp_enabled": True}

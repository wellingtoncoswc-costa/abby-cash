import asyncio
from typing import Annotated

import pyotp
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import CurrentUser, Session
from app.core.redis import redis
from app.core.security import create_access_token, verify_password
from app.domain.users.service import (
    AuthError,
    authenticate,
    check_totp,
    issue_refresh,
    register_user,
    revoke_family,
    rotate_refresh,
)

router = APIRouter(prefix="/auth", tags=["auth"])
MAX_FAILS, MAX_IP_FAILS, MAX_REGISTER_PER_IP, FAIL_TTL = 5, 30, 10, 900
REFRESH_MAX_AGE = 30 * 86400


class RegisterIn(BaseModel):
    email: EmailStr = Field(max_length=254)
    name: str = Field(max_length=200)
    password: str = Field(min_length=10, max_length=128)
    invite_code: str = Field(max_length=64)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    totp: str | None = None


class CodeIn(BaseModel):
    code: str


class PasswordIn(BaseModel):
    password: str = Field(max_length=128)


def _set_cookie(resp: Response, raw: str) -> None:
    resp.set_cookie(
        "refresh_token", raw, max_age=REFRESH_MAX_AGE, path="/auth",
        httponly=True, secure=True, samesite="lax",
    )  # fmt: skip


# ponytail: duplica app.core.redis.incr_ttl (que é atômico); migrar após revisar a semântica do auth
async def _count(key: str) -> int:
    await redis.set(key, 0, ex=FAIL_TTL, nx=True)  # TTL garantido antes do INCR
    return int(await redis.incr(key))


async def _hit(key: str, limit: int) -> None:
    """Conta a tentativa (INCR atômico); acima do limite -> 429."""
    if await _count(key) > limit:
        raise HTTPException(429, "too_many_attempts")


@router.post("/register", status_code=201)
async def register(body: RegisterIn, session: Session, request: Request) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    await _hit(f"register_ip:{ip}", MAX_REGISTER_PER_IP)  # toda tentativa conta
    try:
        user = await register_user(
            session, email=body.email, name=body.name,
            password=body.password, invite_code=body.invite_code,
        )  # fmt: skip
    except ValueError:
        raise HTTPException(400, "invalid_invite") from None
    return {"id": str(user.id), "email": user.email}


@router.post("/login")
async def login(
    body: LoginIn, session: Session, resp: Response, request: Request
) -> dict[str, str]:
    # ponytail: usar IP real (proxy confiável) atrás do Nginx no M8; X-Forwarded-For não é confiável
    ip = request.client.host if request.client else "unknown"
    key = f"login_fail:{body.email.strip().lower()}:{ip}"  # por (email, ip): evita DoS de lockout
    ip_key = f"login_fail_ip:{ip}"
    await _hit(key, MAX_FAILS)  # antes de verificar a senha
    if int(await redis.get(ip_key) or 0) >= MAX_IP_FAILS:  # só falhas contam
        raise HTTPException(429, "too_many_attempts")
    try:
        user = await authenticate(session, body.email, body.password, body.totp)
    except AuthError as e:
        if str(e) == "totp_required":  # senha certa: não é falha, devolve a tentativa
            await redis.decr(key)
        else:
            await _count(ip_key)
        raise HTTPException(401, str(e)) from None
    await redis.delete(key)
    _set_cookie(resp, await issue_refresh(session, user.id))
    return {"access_token": create_access_token(user.id)}


@router.post("/refresh", response_model=dict[str, str])
async def refresh(
    session: Session, resp: Response, refresh_token: Annotated[str | None, Cookie()] = None
) -> dict[str, str] | JSONResponse:
    try:
        user, raw = await rotate_refresh(session, refresh_token or "")
    except AuthError:
        # HTTPException descartaria os headers do resp injetado: devolve a resposta direto
        bad = JSONResponse(status_code=401, content={"detail": "invalid_refresh"})
        bad.delete_cookie("refresh_token", path="/auth")
        return bad
    _set_cookie(resp, raw)
    return {"access_token": create_access_token(user.id)}


@router.post("/logout", status_code=204)
async def logout(
    session: Session, resp: Response, refresh_token: Annotated[str | None, Cookie()] = None
) -> None:
    if refresh_token:
        await revoke_family(session, refresh_token)
    resp.delete_cookie("refresh_token", path="/auth")


@router.post("/2fa/setup")
async def setup_2fa(body: PasswordIn, user: CurrentUser, session: Session) -> dict[str, str]:
    await _hit(f"setup_pw:{user.id}", MAX_FAILS)  # re-auth também é alvo de brute force
    if not await asyncio.to_thread(verify_password, body.password, user.password_hash):
        raise HTTPException(401, "invalid_credentials")
    await redis.delete(f"setup_pw:{user.id}")
    if user.totp_enabled:
        raise HTTPException(409, "totp_already_enabled")
    # ponytail: segredo TOTP em texto puro no banco; cifrar com chave do env no M8
    user.totp_secret = pyotp.random_base32()
    await session.commit()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name="Abby Cash")
    return {"secret": user.totp_secret, "uri": uri}


@router.post("/2fa/verify")
async def verify_2fa(body: CodeIn, user: CurrentUser, session: Session) -> dict[str, bool]:
    key = f"totp_fail:{user.id}"
    await _hit(key, MAX_FAILS)  # incr primeiro: atômico sob concorrência
    if not user.totp_secret or not await check_totp(user, body.code, consume=False):
        raise HTTPException(400, "invalid_code")
    await redis.delete(key)
    user.totp_enabled = True
    await session.commit()
    return {"totp_enabled": True}

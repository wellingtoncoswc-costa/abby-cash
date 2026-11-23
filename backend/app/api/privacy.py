import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.auth import MAX_FAILS, MAX_IP_FAILS, _count, _hit
from app.api.deps import CurrentUser, Session
from app.core.redis import redis
from app.core.security import verify_password
from app.domain.errors import DomainError
from app.domain.privacy import delete_account, export_user_data
from app.domain.users.service import check_totp

router = APIRouter(prefix="/privacy", tags=["privacy"])


class DeleteIn(BaseModel):
    password: str = Field(max_length=128)
    totp: str | None = Field(default=None, max_length=16)


@router.get("/export")
async def export(user: CurrentUser, session: Session) -> Response:
    return Response(
        content=await export_user_data(session, user),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="abby-cash-export.zip"',
            "Cache-Control": "no-store",
        },
    )


async def _refund(key: str) -> None:
    """Devolve a tentativa que o INCR-first já contou (senha certa não é falha).
    Só desfaz o NOSSO +1 (nunca fica abaixo de 0); se o TTL expirou no meio, apaga a chave."""
    if await redis.decr(key) <= 0:
        await redis.delete(key)


@router.delete("/account", status_code=204)
async def delete(body: DeleteIn, user: CurrentUser, session: Session, request: Request) -> None:
    # Só senha ERRADA (e TOTP errado) conta. Por USUÁRIO: INCR-first atômico, devolvido se a
    # senha estava certa e a recusa veio depois (família com membros, totp ausente...).
    # Por IP: teto extra, só incrementa em falha de senha.
    ip = request.client.host if request.client else "unknown"
    key, ip_key = f"delete_pw:{user.id}", f"delete_pw_ip:{ip}"
    await _hit(key, MAX_FAILS)
    if int(await redis.get(ip_key) or 0) >= MAX_IP_FAILS:
        raise HTTPException(429, "too_many_attempts")
    if not await asyncio.to_thread(verify_password, body.password, user.password_hash):
        await _count(ip_key)
        raise HTTPException(401, "invalid_credentials")
    if user.totp_enabled:
        if not body.totp:
            await _refund(key)
            raise HTTPException(401, "totp_required")
        if not await check_totp(user, body.totp):
            await _count(ip_key)
            raise HTTPException(401, "invalid_credentials")
    try:
        await delete_account(session, user)
    except DomainError:
        await _refund(key)
        raise
    await redis.delete(key)

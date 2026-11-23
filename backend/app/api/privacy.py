import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.auth import MAX_FAILS, MAX_IP_FAILS, _hit
from app.api.deps import CurrentUser, Session
from app.core.redis import redis
from app.core.security import verify_password
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


@router.delete("/account", status_code=204)
async def delete(body: DeleteIn, user: CurrentUser, session: Session, request: Request) -> None:
    # senha: teto por USUÁRIO (trocar de IP não zera); IP: teto extra. Ambos INCR-first atômico
    ip = request.client.host if request.client else "unknown"
    key, ip_key = f"delete_pw:{user.id}", f"delete_pw_ip:{ip}"
    await _hit(key, MAX_FAILS)
    await _hit(ip_key, MAX_IP_FAILS)
    if not await asyncio.to_thread(verify_password, body.password, user.password_hash):
        raise HTTPException(401, "invalid_credentials")
    if user.totp_enabled:
        if not body.totp:
            await redis.decr(key)  # senha certa: não é falha
            await redis.decr(ip_key)
            raise HTTPException(401, "totp_required")
        if not await check_totp(user, body.totp):
            raise HTTPException(401, "invalid_credentials")
    await redis.delete(key)
    await delete_account(session, user)

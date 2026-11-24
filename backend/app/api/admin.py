from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, Session, rate_limit
from app.domain.audit import audit
from app.domain.users.service import create_signup_invite

router = APIRouter(prefix="/admin", tags=["admin"])


class SignupInviteOut(BaseModel):
    code: str
    expires_at: datetime


@router.post("/signup-invites", status_code=201, response_model=SignupInviteOut)
async def signup_invite(user: CurrentUser, session: Session) -> SignupInviteOut:
    """O código só aparece nesta resposta (7 dias de validade)."""
    if not user.is_admin:
        raise HTTPException(403, "admin_only")
    await rate_limit(f"signup_invite:{user.id}", 20)
    inv = await create_signup_invite(session, created_by=user.id)
    audit(session, user.id, "signup_invite.create", "signup_invite", inv.id)
    await session.commit()
    return SignupInviteOut(code=inv.code, expires_at=inv.expires_at)

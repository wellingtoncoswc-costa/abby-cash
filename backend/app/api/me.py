from datetime import time
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session, rate_limit
from app.api.schemas import MeOut
from app.domain.errors import DomainError
from app.domain.users.service import update_settings

router = APIRouter(tags=["me"])


class SettingsIn(BaseModel):
    """Só o que for enviado muda; só preferred_channel aceita null (limpa)."""

    tz: str | None = Field(default=None, min_length=1, max_length=64)
    reminder_time: time | None = None
    preferred_channel: str | None = Field(default=None, max_length=32)
    weekly_digest: bool | None = Field(default=None, strict=True)
    default_space_id: UUID | None = None


def _me(user: object) -> MeOut:
    return MeOut.model_validate(user, from_attributes=True)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser) -> MeOut:
    return _me(user)


@router.patch("/me/settings", response_model=MeOut)
async def patch_settings(body: SettingsIn, user: CurrentUser, session: Session) -> MeOut:
    await rate_limit(f"settings:{user.id}", 60)
    fields = body.model_dump(exclude_unset=True)
    if any(v is None for k, v in fields.items() if k != "preferred_channel"):
        raise DomainError("invalid_setting")
    return _me(await update_settings(session, user, fields))

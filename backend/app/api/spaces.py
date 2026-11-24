from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.core.config import get_settings
from app.domain.spaces.models import Space, SpaceMember
from app.domain.spaces.service import (
    accept_space_invite,
    create_family_space,
    create_space_invite,
    remove_member,
)

router = APIRouter(prefix="/spaces", tags=["spaces"])


class FamilyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.get("")
async def list_spaces(user: CurrentUser, session: Session) -> list[dict[str, str]]:
    rows = await session.scalars(
        select(Space)
        .join(SpaceMember, SpaceMember.space_id == Space.id)
        .where(SpaceMember.user_id == user.id)
        .order_by(Space.created_at)
    )
    return [{"id": str(s.id), "type": s.type, "name": s.name} for s in rows]


@router.post("/family", status_code=201)
async def create_family(body: FamilyIn, user: CurrentUser, session: Session) -> dict[str, str]:
    try:
        space = await create_family_space(session, owner_id=user.id, name=body.name)
    except ValueError:
        raise HTTPException(409, "family_space_exists") from None
    return {"id": str(space.id), "name": space.name}


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, user: CurrentUser, session: Session) -> dict[str, str]:
    try:
        space_id = await accept_space_invite(session, token=token, user_id=user.id)
    except ValueError:
        raise HTTPException(404, "not_found") from None
    return {"space_id": str(space_id)}


@router.post("/{space_id}/invites", status_code=201)
async def invite(space_id: UUID, user: CurrentUser, session: Session) -> dict[str, str]:
    inv = await create_space_invite(session, space_id=space_id, created_by=user.id)
    return {"link": f"{get_settings().PUBLIC_BASE_URL}/invite/{inv.token}"}


@router.delete("/{space_id}/members/{user_id}", status_code=204)
async def remove(space_id: UUID, user_id: UUID, user: CurrentUser, session: Session) -> None:
    try:
        await remove_member(session, actor_id=user.id, space_id=space_id, user_id=user_id)
    except ValueError:
        raise HTTPException(409, "cannot_remove_owner") from None

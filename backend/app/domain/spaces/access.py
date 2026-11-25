from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.spaces.models import SpaceMember


async def require_member(session: AsyncSession, user_id: UUID, space_id: UUID) -> SpaceMember:
    # sempre consulta o banco (sem cache): remoção vale na próxima requisição
    member = await session.get(SpaceMember, (space_id, user_id), populate_existing=True)
    if member is None:
        raise HTTPException(status_code=404, detail="not_found")  # 404 não revela existência
    return member


async def is_member(session: AsyncSession, user_id: UUID, space_id: UUID) -> bool:
    return await session.get(SpaceMember, (space_id, user_id), populate_existing=True) is not None


async def require_owner(session: AsyncSession, user_id: UUID, space_id: UUID) -> SpaceMember:
    """Edição estrutural (contas, cartões, metas): só o dono do espaço."""
    member = await require_member(session, user_id, space_id)
    if member.role != "owner":
        raise HTTPException(status_code=403, detail="owner_only")
    return member

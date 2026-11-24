from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.models import Account
from app.domain.spaces.access import is_member, require_member


async def use_account(session: AsyncSession, actor_id: UUID, account_id: UUID) -> Account:
    """Conta que o autor pode usar: precisa ser membro do espaço DONO da conta (spec 14.1)."""
    acc = await session.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="account_not_found")
    if not await is_member(session, actor_id, acc.space_id):
        raise HTTPException(status_code=403, detail="account_forbidden")
    return acc


async def visible_account(session: AsyncSession, viewer_id: UUID, account_id: UUID) -> Account:
    """Conta que o usuário pode ver (GET): não membro = 404, sem revelar existência."""
    acc = await session.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, acc.space_id)
    return acc

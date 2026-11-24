from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit import audit
from app.domain.bills.models import Bill
from app.domain.budgets.models import BudgetCategory
from app.domain.categories.models import Category, CategoryRule
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction

KINDS = {"expense", "income"}
FALLBACK = "Outros"  # categoria padrão: nunca apagada nem renomeada


async def list_categories(
    session: AsyncSession, *, viewer_id: UUID, space_id: UUID
) -> list[Category]:
    await require_member(session, viewer_id, space_id)
    q = select(Category).where(Category.space_id == space_id).order_by(Category.kind, Category.name)
    return list(await session.scalars(q))


async def _taken(
    session: AsyncSession, space_id: UUID, kind: str, name: str, skip: UUID | None
) -> bool:
    q = select(Category.id).where(
        Category.space_id == space_id,
        Category.kind == kind,
        func.lower(Category.name) == name.lower(),
    )
    if skip is not None:
        q = q.where(Category.id != skip)
    return await session.scalar(q.limit(1)) is not None


async def create_category(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, kind: str, name: str,
    icon: str | None = None, color: str | None = None,
) -> Category:  # fmt: skip
    await require_member(session, actor_id, space_id)
    name = name.strip()
    if kind not in KINDS or not 1 <= len(name) <= 60:
        raise DomainError("invalid_category")
    if await _taken(session, space_id, kind, name, None):
        raise DomainError("category_exists")
    cat = Category(space_id=space_id, kind=kind, name=name, icon=icon, color=color)
    session.add(cat)
    await session.flush()
    audit(session, actor_id, "category.create", "category", cat.id, {"space_id": str(space_id)})
    await session.commit()
    return cat


async def _get(session: AsyncSession, actor_id: UUID, category_id: UUID) -> Category:
    cat = await session.get(Category, category_id)
    if cat is None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, actor_id, cat.space_id)
    return cat


async def update_category(
    session: AsyncSession, *, actor_id: UUID, category_id: UUID, fields: dict[str, str | None]
) -> Category:
    """fields: só as chaves enviadas (name, icon, color); a categoria padrão não renomeia."""
    cat = await _get(session, actor_id, category_id)
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not 1 <= len(name) <= 60:
            raise DomainError("invalid_category")
        if cat.name == FALLBACK and name != FALLBACK:
            raise DomainError("default_category")
        if await _taken(session, cat.space_id, cat.kind, name, cat.id):
            raise DomainError("category_exists")
        cat.name = name
    for k in ("icon", "color"):
        if k in fields:
            setattr(cat, k, fields[k])
    audit(session, actor_id, "category.update", "category", cat.id, {"space_id": str(cat.space_id)})
    await session.commit()
    return cat


async def delete_category(
    session: AsyncSession, *, actor_id: UUID, category_id: UUID, reassign_to: UUID | None = None
) -> None:
    cat = await _get(session, actor_id, category_id)
    if cat.name == FALLBACK:
        raise DomainError("default_category")
    used = (
        await session.scalar(select(func.count()).where(Transaction.category_id == cat.id)) or 0
    ) + (await session.scalar(select(func.count()).where(Bill.category_id == cat.id)) or 0)
    if reassign_to is not None:
        dest = await session.get(Category, reassign_to)
        if (
            dest is None
            or dest.id == cat.id
            or dest.space_id != cat.space_id
            or dest.kind != cat.kind
        ):
            raise DomainError("invalid_category")
        for model in (Transaction, Bill):
            await session.execute(
                update(model).where(model.category_id == cat.id).values(category_id=dest.id)
            )
    elif used:
        raise DomainError("category_in_use")
    # limites de orçamento e regras aprendidas da categoria somem com ela
    await session.execute(delete(BudgetCategory).where(BudgetCategory.category_id == cat.id))
    await session.execute(delete(CategoryRule).where(CategoryRule.category_id == cat.id))
    audit(session, actor_id, "category.delete", "category", cat.id,
          {"space_id": str(cat.space_id), "reassigned": used if reassign_to else 0})  # fmt: skip
    await session.delete(cat)
    await session.commit()

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.accounts.models import Account
from app.domain.cards.models import CreditCard
from app.domain.categories.models import Category, CategoryRule
from app.domain.goals.models import Goal
from app.domain.spaces.access import require_member
from app.domain.spaces.models import Space, SpaceMember


@dataclass(frozen=True)
class CtxCategory:
    id: UUID
    name: str
    kind: str  # expense | income


@dataclass(frozen=True)
class CtxAccount:
    id: UUID
    name: str
    type: str  # checking | wallet | savings
    space_id: UUID


@dataclass(frozen=True)
class CtxCard:
    id: UUID
    name: str
    space_id: UUID


@dataclass(frozen=True)
class CtxGoal:
    id: UUID
    name: str


@dataclass(frozen=True)
class SpaceContext:
    """O que o interpretador (e os fluxos) sabem do espaço-alvo. Categorias e metas são do espaço;
    contas e cartões são os que o usuário PODE USAR (qualquer espaço de que é membro)."""

    space_id: UUID
    space_name: str
    categories: list[CtxCategory]
    accounts: list[CtxAccount]
    cards: list[CtxCard]
    goals: list[CtxGoal]
    rules: list[tuple[str, str]]  # (estabelecimento normalizado, nome da categoria)
    default_account_id: UUID | None
    today: date
    tz: str


async def load_space_context(
    session: AsyncSession, *, user_id: UUID, space_id: UUID, today: date, tz: str
) -> SpaceContext:
    member = await require_member(session, user_id, space_id)  # isolamento antes de tudo
    mine = list(
        await session.scalars(select(SpaceMember.space_id).where(SpaceMember.user_id == user_id))
    )
    space = await session.get(Space, space_id)
    assert space is not None
    cats = await session.scalars(
        select(Category).where(Category.space_id == space_id).order_by(Category.name)
    )
    accs = await session.scalars(
        select(Account).where(Account.space_id.in_(mine)).order_by(Account.name)
    )
    cards = await session.scalars(
        select(CreditCard).where(CreditCard.space_id.in_(mine)).order_by(CreditCard.name)
    )
    goals = await session.scalars(select(Goal).where(Goal.space_id == space_id).order_by(Goal.name))
    rules = await session.execute(
        select(CategoryRule.merchant_norm, Category.name)
        .join(Category, Category.id == CategoryRule.category_id)
        .where(CategoryRule.space_id == space_id)
        .limit(100)
    )
    return SpaceContext(
        space_id=space_id,
        space_name=space.name,
        categories=[CtxCategory(c.id, c.name, c.kind) for c in cats],
        accounts=[CtxAccount(a.id, a.name, a.type, a.space_id) for a in accs],
        cards=[CtxCard(c.id, c.name, c.space_id) for c in cards],
        goals=[CtxGoal(g.id, g.name) for g in goals],
        rules=[(m, n) for m, n in rules],
        default_account_id=member.default_account_id,
        today=today,
        tz=tz,
    )

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.categories.models import Category
from app.domain.errors import DomainError
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction


async def check_common(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, type: str, amount_cents: int,
    category_id: UUID | None,
) -> None:  # fmt: skip
    """Valor > 0, autor membro do espaço, categoria do mesmo espaço e do tipo certo."""
    if amount_cents <= 0:
        raise DomainError("amount_must_be_positive")
    await require_member(session, actor_id, space_id)
    if category_id is not None:
        cat = await session.get(Category, category_id)
        wanted = "income" if type == "income" else "expense"
        if cat is None or cat.space_id != space_id or (type != "transfer" and cat.kind != wanted):
            raise DomainError("invalid_category")


def signed(tx: Transaction, account_id: UUID) -> int:
    """Efeito do lançamento no saldo da conta: receita +, despesa −, transferência −/+."""
    if tx.type == "transfer":
        if tx.account_id == account_id:
            return -tx.amount_cents
        return tx.amount_cents if tx.counter_account_id == account_id else 0
    if tx.account_id != account_id:
        return 0
    return tx.amount_cents if tx.type == "income" else -tx.amount_cents

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dates import local_today, to_local_date
from app.domain.accounts.access import use_account
from app.domain.audit import audit, snap
from app.domain.categories.models import Category
from app.domain.errors import DomainError
from app.domain.goals.models import GoalPocket
from app.domain.pockets.models import CdiRate, Pocket, PocketMovement, PocketYieldPosting
from app.domain.spaces.access import require_member
from app.domain.transactions.models import Transaction
from app.domain.transactions.rules import check_common
from app.domain.transactions.service import account_balance

YIELD_CATEGORY = "Rendimentos"


@dataclass(frozen=True)
class PocketStats:
    balance: int
    pending: int  # rendimento creditado na caixinha e ainda não lançado como receita
    month_yield: int


def _tz() -> str:
    return get_settings().DEFAULT_TZ


def _signed() -> Any:
    return case(
        (PocketMovement.kind == "withdraw", -PocketMovement.amount_cents),
        else_=PocketMovement.amount_cents,
    )


async def visible_pocket(
    session: AsyncSession, viewer_id: UUID, pocket_id: UUID, *, lock: bool = False
) -> Pocket:
    pocket = await session.get(Pocket, pocket_id, with_for_update=lock)
    if pocket is None or pocket.closed_at is not None:
        raise HTTPException(status_code=404, detail="not_found")
    await require_member(session, viewer_id, pocket.space_id)
    return pocket


async def pocket_stats(session: AsyncSession, pocket_id: UUID, today: date) -> PocketStats:
    base = select(func.coalesce(func.sum(PocketMovement.amount_cents), 0)).where(
        PocketMovement.pocket_id == pocket_id, PocketMovement.kind == "accrual"
    )
    accrued = int(await session.scalar(base) or 0)
    month = int(
        await session.scalar(base.where(PocketMovement.ref_date >= today.replace(day=1))) or 0
    )
    balance = int(
        await session.scalar(
            select(func.coalesce(func.sum(_signed()), 0)).where(
                PocketMovement.pocket_id == pocket_id
            )
        )
        or 0
    )
    posted = int(
        await session.scalar(
            select(func.coalesce(func.sum(PocketYieldPosting.amount_cents), 0)).where(
                PocketYieldPosting.pocket_id == pocket_id
            )
        )
        or 0
    )
    return PocketStats(balance, accrued - posted, month)


async def account_pockets_cents(session: AsyncSession, account_id: UUID) -> int:
    """Dinheiro da conta reservado nas caixinhas (sem o rendimento ainda não lançado)."""
    ids = await session.scalars(select(Pocket.id).where(Pocket.account_id == account_id))
    today = local_today(_tz())
    total = 0
    for pid in ids:
        st = await pocket_stats(session, pid, today)
        total += st.balance - st.pending
    return total


async def create_pocket(
    session: AsyncSession, *, actor_id: UUID, space_id: UUID, account_id: UUID, name: str,
    cdi_bp: int,
) -> Pocket:  # fmt: skip
    await require_member(session, actor_id, space_id)
    acc = await use_account(session, actor_id, account_id)
    if acc.space_id != space_id:
        raise HTTPException(status_code=404, detail="account_not_found")
    pocket = Pocket(space_id=space_id, account_id=account_id, name=name, cdi_bp=cdi_bp)
    session.add(pocket)
    await session.flush()
    audit(session, actor_id, "pocket.create", "pocket", pocket.id,
          {"space_id": str(space_id), "cdi_bp": cdi_bp})  # fmt: skip
    await session.commit()
    return pocket


async def update_pocket(
    session: AsyncSession, *, actor_id: UUID, pocket_id: UUID, fields: dict[str, Any]
) -> Pocket:
    """fields: name, cdi_bp. Nova taxa vale dos próximos dias em diante (accruals já gravados)."""
    pocket = await visible_pocket(session, actor_id, pocket_id, lock=True)
    before = snap(pocket, fields)
    for k, v in fields.items():
        setattr(pocket, k, v)
    audit(session, actor_id, "pocket.update", "pocket", pocket.id,
          {"space_id": str(pocket.space_id), "before": before,
           "after": snap(pocket, fields)})  # fmt: skip
    await session.commit()
    return pocket


async def delete_pocket(session: AsyncSession, *, actor_id: UUID, pocket_id: UUID) -> None:
    pocket = await visible_pocket(session, actor_id, pocket_id, lock=True)
    if (await pocket_stats(session, pocket.id, local_today(_tz()))).balance != 0:
        raise DomainError("pocket_has_balance")
    pocket.closed_at = datetime.now(UTC)
    await session.execute(delete(GoalPocket).where(GoalPocket.pocket_id == pocket.id))
    audit(
        session, actor_id, "pocket.delete", "pocket", pocket.id, {"space_id": str(pocket.space_id)}
    )
    await session.commit()


async def _last_accrual(session: AsyncSession, pocket_id: UUID) -> date | None:
    return await session.scalar(
        select(func.max(PocketMovement.ref_date)).where(
            PocketMovement.pocket_id == pocket_id, PocketMovement.kind == "accrual"
        )
    )


async def _move(
    session: AsyncSession, *, actor_id: UUID, pocket_id: UUID, kind: str, amount_cents: int,
    on: date | None, origin: str, source_message_id: str | None,
) -> PocketMovement:  # fmt: skip
    pocket = await visible_pocket(session, actor_id, pocket_id, lock=True)
    today = local_today(_tz())
    on = on or today
    await check_common(
        session, actor_id=actor_id, space_id=pocket.space_id, type="transfer",
        amount_cents=amount_cents, category_id=None, occurred_on=on,
    )  # fmt: skip
    last = await _last_accrual(session, pocket.id)
    if on > today or (last is not None and on < last):
        raise DomainError("invalid_date")  # movimento no passado mudaria rendimento já creditado
    if kind == "deposit":
        acc = await use_account(session, actor_id, pocket.account_id)
        await session.refresh(acc, with_for_update=True)  # serializa depósitos da mesma conta
        balance = await account_balance(session, acc.id)
        if amount_cents > balance - await account_pockets_cents(session, acc.id):
            raise HTTPException(status_code=409, detail="insufficient_available")
    else:
        await accrue_pocket(session, pocket, today)
        await post_yield(session, pocket, today, include_current=True)
        if amount_cents > (await pocket_stats(session, pocket.id, today)).balance:
            raise DomainError("insufficient_balance")
    mv = PocketMovement(
        pocket_id=pocket.id,
        kind=kind,
        amount_cents=amount_cents,
        occurred_on=on,
        origin=origin,
        source_message_id=source_message_id,
    )
    session.add(mv)
    await session.flush()
    audit(session, actor_id, f"pocket.{kind}", "pocket", pocket.id,
          {"movement_id": str(mv.id), "amount_cents": amount_cents})  # fmt: skip
    await session.commit()
    return mv


async def deposit(
    session: AsyncSession,
    *,
    actor_id: UUID,
    pocket_id: UUID,
    amount_cents: int,
    on: date | None = None,
    origin: str = "web",
    source_message_id: str | None = None,
) -> PocketMovement:
    return await _move(session, actor_id=actor_id, pocket_id=pocket_id, kind="deposit",
                       amount_cents=amount_cents, on=on, origin=origin,
                       source_message_id=source_message_id)  # fmt: skip


async def withdraw(
    session: AsyncSession,
    *,
    actor_id: UUID,
    pocket_id: UUID,
    amount_cents: int,
    on: date | None = None,
    origin: str = "web",
    source_message_id: str | None = None,
) -> PocketMovement:
    return await _move(session, actor_id=actor_id, pocket_id=pocket_id, kind="withdraw",
                       amount_cents=amount_cents, on=on, origin=origin,
                       source_message_id=source_message_id)  # fmt: skip


async def list_movements(
    session: AsyncSession, *, viewer_id: UUID, pocket_id: UUID
) -> list[PocketMovement]:
    await visible_pocket(session, viewer_id, pocket_id)
    q = select(PocketMovement).where(PocketMovement.pocket_id == pocket_id)
    return list(await session.scalars(q.order_by(PocketMovement.occurred_on.desc(),
                                                 PocketMovement.created_at.desc())))  # fmt: skip


async def accrue_pocket(session: AsyncSession, pocket: Pocket, today: date) -> int:
    """Grava o rendimento dos dias com CDI ainda não creditados (idempotente). Não faz commit."""
    created = to_local_date(pocket.created_at, _tz())
    done = select(PocketMovement.ref_date).where(
        PocketMovement.pocket_id == pocket.id, PocketMovement.kind == "accrual"
    )
    rates = await session.scalars(
        select(CdiRate)
        .where(CdiRate.on_date > created, CdiRate.on_date <= today, CdiRate.on_date.not_in(done))
        .order_by(CdiRate.on_date)
    )
    n = 0
    for r in rates:
        await session.flush()
        # saldo no início do dia r.on_date: juros compostos dia a dia
        # ponytail: 1 query por dia; se o backfill ficar grande, acumular em memória
        bal = int(
            await session.scalar(
                select(func.coalesce(func.sum(_signed()), 0)).where(
                    PocketMovement.pocket_id == pocket.id, PocketMovement.occurred_on < r.on_date
                )
            )
            or 0
        )
        cents = int(
            (Decimal(bal) * r.daily_pct / 100 * pocket.cdi_bp / 10000).quantize(
                Decimal(1), ROUND_HALF_EVEN
            )
        )
        if cents > 0:
            session.add(PocketMovement(pocket_id=pocket.id, kind="accrual", amount_cents=cents,
                                       occurred_on=r.on_date, ref_date=r.on_date))  # fmt: skip
            n += 1
    await session.flush()
    return n


async def _yield_category(session: AsyncSession, space_id: UUID) -> UUID:
    cid = await session.scalar(
        select(Category.id).where(
            Category.space_id == space_id,
            Category.kind == "income",
            Category.name == YIELD_CATEGORY,
        )
    )
    if cid is None:
        cat = Category(space_id=space_id, kind="income", name=YIELD_CATEGORY)
        session.add(cat)
        await session.flush()
        cid = cat.id
    return cid


async def post_yield(
    session: AsyncSession, pocket: Pocket, today: date, *, include_current: bool = False
) -> None:
    """Uma receita "Rendimento" por mês (meses fechados; `include_current` no resgate).
    Se um mês já lançado ganhou novos dias, a mesma receita é ajustada. Não faz commit."""
    month = func.to_char(PocketMovement.ref_date, "YYYY-MM")
    cur = f"{today:%Y-%m}"
    q = (
        select(month, func.sum(PocketMovement.amount_cents), func.max(PocketMovement.ref_date))
        .where(PocketMovement.pocket_id == pocket.id, PocketMovement.kind == "accrual")
        .group_by(month)
    )
    for m, total, last in (await session.execute(q)).all():
        if m == cur and not include_current or m > cur:
            continue
        posting = await session.get(PocketYieldPosting, (pocket.id, m))
        if posting is None:
            tx = Transaction(
                space_id=pocket.space_id, type="income", amount_cents=int(total), occurred_on=last,
                description=f"Rendimento — {pocket.name}", account_id=pocket.account_id,
                category_id=await _yield_category(session, pocket.space_id), origin="system",
            )  # fmt: skip
            session.add(tx)
            await session.flush()
            session.add(PocketYieldPosting(pocket_id=pocket.id, month=m, transaction_id=tx.id,
                                           amount_cents=int(total)))  # fmt: skip
        elif posting.amount_cents != total:
            old = await session.get(Transaction, posting.transaction_id)
            if old is not None:
                old.amount_cents, old.occurred_on = int(total), last
            posting.amount_cents = int(total)
    await session.flush()


async def accrue_all(session: AsyncSession, pocket_id: UUID, today: date) -> None:
    """Job: rendimento + lançamento mensal de uma caixinha, numa transação."""
    pocket = await session.get(Pocket, pocket_id, with_for_update=True)
    if pocket is None or pocket.closed_at is not None:
        return
    await accrue_pocket(session, pocket, today)
    await post_yield(session, pocket, today)
    await session.commit()

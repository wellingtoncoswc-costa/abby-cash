from datetime import date

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domain.bills.recurrence import monthly
from app.domain.recurring.models import RecurringPosting
from app.domain.recurring.service import create_item
from app.domain.transactions.models import Transaction
from app.jobs.recurring import post_recurring_job
from tests.factories import make_account, make_user


async def test_job_posts_once_and_survives_a_broken_item(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=10_000)
    ok = await create_item(
        session, actor_id=a.id, space_id=a.default_space_id, type="expense", description="Aluguel",
        amount_cents=1_000, account_id=acc.id, rule=monthly(5), starts_on=date(2026, 11, 1),
    )  # fmt: skip
    await post_recurring_job(today=date(2026, 11, 25))
    await post_recurring_job(today=date(2026, 11, 25))  # idempotente
    async with SessionLocal() as s:
        txs = list(await s.scalars(select(Transaction).where(Transaction.origin == "recurring")))
        posts = list(await s.scalars(select(RecurringPosting)))
    assert [(t.amount_cents, t.occurred_on, t.account_id) for t in txs] == [
        (1_000, date(2026, 11, 5), acc.id)
    ]
    assert [(p.item_id, p.transaction_id) for p in posts] == [(ok.id, txs[0].id)]

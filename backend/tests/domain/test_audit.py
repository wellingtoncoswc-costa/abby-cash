from datetime import date

from sqlalchemy import select

from app.domain.accounts.service import create_account
from app.domain.audit import AuditLog, audit
from app.domain.bills.service import create_bill
from app.domain.budgets.service import set_budget
from app.domain.cards.service import register_card_purchase
from app.domain.goals.service import contribute, create_goal, withdraw
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.service import create_transaction
from tests.factories import make_card, make_user

D = date(2026, 11, 10)


async def test_audit_helper_adds_a_row(session):
    a = await make_user(session, "a@x.com")
    audit(session, a.id, "x.did", "thing", a.id, {"k": 1})
    await session.commit()
    row = await session.scalar(select(AuditLog))
    assert (row.actor_id, row.action, row.entity, row.entity_id) == (a.id, "x.did", "thing", a.id)
    assert row.data == {"k": 1} and row.created_at is not None


async def test_services_write_audit_rows(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await create_account(
        session, actor_id=a.id, space_id=sp, type="checking", name="Itaú",
        initial_balance_cents=100_000,
    )  # fmt: skip
    tx = await create_transaction(
        session, actor_id=a.id, space_id=sp, type="expense", amount_cents=1_000, occurred_on=D,
        account_id=acc.id,
    )  # fmt: skip
    card = await make_card(session, a, sp)
    (buy,) = await register_card_purchase(
        session, actor_id=a.id, space_id=sp, card_id=card.id, amount_cents=5_000, occurred_on=D
    )  # fmt: skip
    bill = await create_bill(
        session, actor_id=a.id, space_id=sp, description="Luz", amount_cents=2_000, due_on=D
    )  # fmt: skip
    await pay_bill(session, actor_id=a.id, bill_id=bill.id, account_id=acc.id, paid_on=D)
    await pay_invoice(
        session, actor_id=a.id, invoice_id=buy.invoice_id, account_id=acc.id, paid_on=D,
        amount_cents=5_000,
    )  # fmt: skip
    await set_budget(session, actor_id=a.id, space_id=sp, month=D, limit_cents=10_000)
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=9_000, created_on=D
    )  # fmt: skip
    await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=500, on=D
    )  # fmt: skip
    await withdraw(
        session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=100, on=D
    )  # fmt: skip
    rows = (await session.scalars(select(AuditLog))).all()
    assert {r.action for r in rows} >= {
        "account.create", "transaction.create", "card.create", "card.purchase", "bill.create",
        "bill.pay", "invoice.pay", "budget.set", "goal.create", "goal.contribute",
        "goal.withdraw",
    }  # fmt: skip
    assert all(r.actor_id == a.id for r in rows)
    created = next(r for r in rows if r.action == "transaction.create")
    assert created.entity_id == tx.id and created.data["amount_cents"] == 1_000

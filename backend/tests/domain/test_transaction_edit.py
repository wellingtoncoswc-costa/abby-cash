from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.money import MAX_CENTS
from app.domain.audit import AuditLog
from app.domain.bills.models import Bill
from app.domain.bills.service import create_bill
from app.domain.cards.models import Invoice
from app.domain.cards.service import invoice_total, register_card_purchase
from app.domain.errors import DomainError
from app.domain.goals.service import contribute, create_goal, goal_saved, withdraw
from app.domain.payments import pay_bill, pay_invoice
from app.domain.transactions.models import Transaction
from app.domain.transactions.service import (
    account_balance,
    create_transaction,
    delete_transaction,
    update_transaction,
)
from tests.factories import category_id, make_account, make_card, make_family, make_user

D = date(2026, 11, 10)


async def expense(session, user, space, acc, amount=10_000):
    return await create_transaction(
        session, actor_id=user.id, space_id=space, type="expense", amount_cents=amount,
        occurred_on=D, description="x", account_id=acc.id,
    )  # fmt: skip


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(Transaction))


async def test_update_changes_fields_and_balance(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    tx = await expense(session, ana, sp, acc)
    lazer = await category_id(session, sp, "Lazer")
    out = await update_transaction(
        session, actor_id=ana.id, tx_id=tx.id, amount_cents=25_000, category_id=lazer,
        description="cinema", merchant="Cine", occurred_on=date(2026, 11, 9),
    )  # fmt: skip
    assert (out.amount_cents, out.category_id, out.description, out.merchant) == (
        25_000, lazer, "cinema", "Cine",
    )  # fmt: skip
    assert out.occurred_on == date(2026, 11, 9)
    assert await account_balance(session, acc.id) == 75_000


async def test_update_validates_like_create(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    sp = ana.default_space_id
    tx = await expense(session, ana, sp, await make_account(session, sp))
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await update_transaction(session, actor_id=ana.id, tx_id=tx.id, amount_cents=0)
    foreign = await category_id(session, bia.default_space_id, "Lazer")
    with pytest.raises(DomainError, match="invalid_category"):
        await update_transaction(session, actor_id=ana.id, tx_id=tx.id, category_id=foreign)


async def test_payments_and_transfers_are_not_editable(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    bill = await create_bill(
        session, actor_id=ana.id, space_id=sp, description="Luz", amount_cents=5_000, due_on=D
    )
    paid = await pay_bill(session, actor_id=ana.id, bill_id=bill.id, account_id=acc.id, paid_on=D)
    with pytest.raises(DomainError, match="not_editable"):
        await update_transaction(session, actor_id=ana.id, tx_id=paid.id, amount_cents=1)


async def test_only_author_or_space_owner_may_edit_and_delete(session):
    husband, wife = await make_user(session, "h@x.com"), await make_user(session, "w@x.com")
    outsider = await make_user(session, "o@x.com")
    fam = await make_family(session, husband, wife)
    acc = await make_account(session, fam.id)
    by_husband = await expense(session, husband, fam.id, acc)
    by_wife = await expense(session, wife, fam.id, acc)
    with pytest.raises(HTTPException) as e:  # membro comum não mexe no lançamento dos outros
        await update_transaction(session, actor_id=wife.id, tx_id=by_husband.id, amount_cents=1)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await delete_transaction(session, actor_id=wife.id, tx_id=by_husband.id)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:  # quem não é do espaço nem descobre que existe
        await delete_transaction(session, actor_id=outsider.id, tx_id=by_wife.id)
    assert e.value.status_code == 404
    out = await update_transaction(session, actor_id=husband.id, tx_id=by_wife.id, amount_cents=7)
    assert out.amount_cents == 7  # dono do espaço pode
    await delete_transaction(session, actor_id=wife.id, tx_id=by_wife.id)  # autora pode
    assert await count(session) == 1


async def test_update_card_purchase_amount_resyncs_invoice_bill(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    card = await make_card(session, ana, sp)  # fecha dia 10, vence dia 20
    [tx] = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=10_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    await update_transaction(session, actor_id=ana.id, tx_id=tx.id, amount_cents=15_000)
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == tx.invoice_id))
    assert bill is not None and bill.amount_cents == 15_000
    assert await invoice_total(session, tx.invoice_id) == 15_000
    with pytest.raises(DomainError, match="card_date_not_editable"):
        await update_transaction(
            session, actor_id=ana.id, tx_id=tx.id, occurred_on=date(2026, 11, 20)
        )


async def test_installment_group_edit_rules(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    card = await make_card(session, ana, sp)
    txs = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=30_000,
        occurred_on=date(2026, 11, 5), installments=3,
    )  # fmt: skip
    with pytest.raises(DomainError, match="installment_group_not_editable"):
        await update_transaction(session, actor_id=ana.id, tx_id=txs[0].id, amount_cents=1)
    lazer = await category_id(session, sp, "Lazer")
    await update_transaction(session, actor_id=ana.id, tx_id=txs[0].id, category_id=lazer)
    cats = list(await session.scalars(select(Transaction.category_id)))
    assert cats == [lazer] * 3  # categoria vale para o grupo inteiro


async def test_delete_restores_balance(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    tx = await expense(session, ana, sp, acc, 30_000)
    assert await account_balance(session, acc.id) == 70_000
    deleted = await delete_transaction(session, actor_id=ana.id, tx_id=tx.id)
    assert [d.id for d in deleted] == [tx.id] and deleted[0].amount_cents == 30_000
    assert await account_balance(session, acc.id) == 100_000


async def test_delete_installment_group_removes_all_and_resyncs_invoices(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    card = await make_card(session, ana, sp)
    txs = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=30_000,
        occurred_on=date(2026, 11, 5), installments=3,
    )  # fmt: skip
    deleted = await delete_transaction(session, actor_id=ana.id, tx_id=txs[1].id)
    assert len(deleted) == 3 and await count(session) == 0
    bills = list(await session.scalars(select(Bill).where(Bill.kind == "invoice")))
    assert len(bills) == 3 and [b.amount_cents for b in bills] == [0, 0, 0]
    assert await session.scalar(select(func.count()).select_from(Invoice)) == 3  # faturas ficam


async def test_delete_invoice_payment_reopens_the_bill(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    card = await make_card(session, ana, sp)
    [buy] = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=10_000,
        occurred_on=date(2026, 11, 5),
    )  # fmt: skip
    paid = await pay_invoice(
        session, actor_id=ana.id, invoice_id=buy.invoice_id, account_id=acc.id, paid_on=D,
        amount_cents=10_000,
    )  # fmt: skip
    bill = await session.scalar(select(Bill).where(Bill.invoice_id == buy.invoice_id))
    assert bill.status == "paid"
    await delete_transaction(session, actor_id=ana.id, tx_id=paid.id)
    await session.refresh(bill)
    assert bill.status == "open" and await account_balance(session, acc.id) == 100_000


async def test_delete_bill_payment_reopens_the_bill(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    bill = await create_bill(
        session, actor_id=ana.id, space_id=sp, description="Luz", amount_cents=5_000, due_on=D
    )
    paid = await pay_bill(session, actor_id=ana.id, bill_id=bill.id, account_id=acc.id, paid_on=D)
    await session.refresh(bill)
    assert bill.status == "paid"
    await delete_transaction(session, actor_id=ana.id, tx_id=paid.id)
    await session.refresh(bill)
    assert bill.status == "open"


async def test_edit_and_delete_are_audited(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    tx = await expense(session, ana, sp, await make_account(session, sp))
    await update_transaction(session, actor_id=ana.id, tx_id=tx.id, amount_cents=5_000)
    await delete_transaction(session, actor_id=ana.id, tx_id=tx.id)
    actions = list(
        await session.scalars(select(AuditLog.action).where(AuditLog.entity == "transaction"))
    )
    assert {"transaction.create", "transaction.update", "transaction.delete"} <= set(actions)


async def test_delete_goal_contribution_rules(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    goal = await create_goal(
        session, actor_id=ana.id, space_id=sp, name="Viagem", target_cents=50_000, created_on=D
    )
    c1 = await contribute(
        session, actor_id=ana.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=10_000, on=D
    )
    c1_id, goal_id, uid = c1.id, goal.id, ana.id
    await withdraw(
        session, actor_id=ana.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=8_000, on=D
    )
    with pytest.raises(DomainError, match="insufficient_saved"):  # saldo da meta ficaria negativo
        await delete_transaction(session, actor_id=uid, tx_id=c1_id)
    assert await goal_saved(session, goal_id) == 2_000
    with pytest.raises(DomainError, match="not_editable"):
        await update_transaction(session, actor_id=uid, tx_id=c1_id, amount_cents=1)


async def test_delete_goal_contribution_ok(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    goal = await create_goal(
        session, actor_id=ana.id, space_id=sp, name="Viagem", target_cents=50_000, created_on=D
    )
    c1 = await contribute(
        session, actor_id=ana.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=10_000, on=D
    )
    await delete_transaction(session, actor_id=ana.id, tx_id=c1.id)
    assert await goal_saved(session, goal.id) == 0


async def test_update_rejects_amount_above_max_and_missing_tx(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    tx = await expense(session, ana, sp, await make_account(session, sp))
    with pytest.raises(DomainError, match="amount_too_large"):
        await update_transaction(session, actor_id=ana.id, tx_id=tx.id, amount_cents=MAX_CENTS + 1)
    with pytest.raises(HTTPException) as e:
        await delete_transaction(session, actor_id=ana.id, tx_id=uuid4())
    assert e.value.status_code == 404


async def test_non_member_edit_is_404(session):
    ana, bob = await make_user(session, "ana@x.com"), await make_user(session, "bob@x.com")
    sp = ana.default_space_id
    tx = await expense(session, ana, sp, await make_account(session, sp))
    with pytest.raises(HTTPException) as e:
        await update_transaction(session, actor_id=bob.id, tx_id=tx.id, amount_cents=1)
    assert e.value.status_code == 404


async def _race(actor_id, *calls):
    """Cada chamada roda na própria sessão, ao mesmo tempo; devolve resultados ou exceções."""
    import asyncio

    from app.core.db import SessionLocal

    async def run(fn, **kw):
        async with SessionLocal() as s:
            return await fn(s, actor_id=actor_id, **kw)

    return await asyncio.wait_for(
        asyncio.gather(*(run(fn, **kw) for fn, kw in calls), return_exceptions=True), 10
    )


def _is_404(r) -> bool:
    return isinstance(r, HTTPException) and r.status_code == 404


async def test_concurrent_delete_of_same_transaction_one_wins(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    tx = await expense(session, ana, sp, acc, 30_000)
    res = await _race(ana.id, *[(delete_transaction, {"tx_id": tx.id})] * 2)
    assert sum(isinstance(r, list) for r in res) == 1 and sum(_is_404(r) for r in res) == 1
    assert await count(session) == 0 and await account_balance(session, acc.id) == 100_000


async def test_concurrent_delete_of_same_installment_group_one_wins(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    card = await make_card(session, ana, sp)
    txs = await register_card_purchase(
        session, actor_id=ana.id, space_id=sp, card_id=card.id, amount_cents=30_000,
        occurred_on=date(2026, 11, 5), installments=3,
    )  # fmt: skip
    res = await _race(  # parcelas diferentes do mesmo grupo: travam na mesma ordem, sem deadlock
        ana.id,
        (delete_transaction, {"tx_id": txs[0].id}),
        (delete_transaction, {"tx_id": txs[2].id}),
    )
    assert sum(isinstance(r, list) and len(r) == 3 for r in res) == 1
    assert sum(_is_404(r) for r in res) == 1
    assert await count(session) == 0


async def test_concurrent_delete_and_edit_serialize(session):
    ana = await make_user(session, "ana@x.com")
    sp = ana.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    tx = await expense(session, ana, sp, acc, 30_000)
    res = await _race(
        ana.id, (delete_transaction, {"tx_id": tx.id}),
        (update_transaction, {"tx_id": tx.id, "amount_cents": 5_000}),
    )  # fmt: skip
    assert isinstance(res[0], list)  # a exclusão sempre vence no fim
    assert not isinstance(res[1], Exception) or _is_404(res[1])  # edição: aplicada antes, ou 404
    assert await count(session) == 0 and await account_balance(session, acc.id) == 100_000

from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.domain.errors import DomainError
from app.domain.transactions.service import (
    account_balance,
    create_transaction,
    list_transactions,
    normalize_merchant,
)
from tests.factories import category_id, make_account, make_family, make_user

D = date(2026, 11, 10)


async def _tx(session, user, acc, amount, *, type="expense", on=D, cat=None, space=None,
              counter=None, description="x"):  # fmt: skip
    return await create_transaction(
        session, actor_id=user.id, space_id=space or user.default_space_id, type=type,
        amount_cents=amount, occurred_on=on, description=description, category_id=cat,
        account_id=acc.id, counter_account_id=counter.id if counter else None,
    )  # fmt: skip


async def test_balance_formula_with_transfers(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    one = await make_account(session, sp, name="Um", initial=100_000)
    two = await make_account(session, sp, name="Dois")
    await _tx(session, a, one, 50_000, type="income")
    await _tx(session, a, one, 20_000)
    await _tx(session, a, one, 30_000, type="transfer", counter=two)
    await _tx(session, a, two, 10_000, type="transfer", counter=one)
    assert await account_balance(session, one.id) == 100_000 + 50_000 - 20_000 - 30_000 + 10_000
    assert await account_balance(session, two.id) == 30_000 - 10_000


async def test_cannot_use_account_from_space_user_is_not_member(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    theirs = await make_account(session, a.default_space_id)
    mine = await make_account(session, b.default_space_id)
    with pytest.raises(HTTPException) as e:
        await _tx(session, b, theirs, 1_000)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:  # destino de transferência também conta
        await _tx(session, b, mine, 1_000, type="transfer", counter=theirs)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await create_transaction(
            session, actor_id=b.id, space_id=b.default_space_id, type="expense",
            amount_cents=1, occurred_on=D, account_id=uuid4(),
        )  # fmt: skip
    assert e.value.status_code == 404


async def test_member_can_use_shared_account_in_own_personal_space(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    shared = await make_account(session, fam.id, name="Conjunta")
    tx = await _tx(session, h, shared, 1_000)  # lançamento no espaço pessoal do h
    assert tx.space_id == h.default_space_id and tx.account_id == shared.id
    assert await account_balance(session, shared.id) == -1_000


async def test_non_member_cannot_create_or_list_in_space(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, b.default_space_id)
    with pytest.raises(HTTPException) as e:
        await _tx(session, b, acc, 1_000, space=a.default_space_id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await list_transactions(session, viewer_id=b.id, space_id=a.default_space_id)
    assert e.value.status_code == 404


async def test_amount_must_be_positive(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id)
    for bad in (0, -5):
        with pytest.raises(DomainError, match="amount_must_be_positive"):
            await _tx(session, a, acc, bad)
    assert await list_transactions(session, viewer_id=a.id, space_id=a.default_space_id) == []


async def test_category_must_belong_to_space_and_match_kind(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id)
    foreign = await category_id(session, b.default_space_id)
    with pytest.raises(DomainError, match="invalid_category"):
        await _tx(session, a, acc, 1_000, cat=foreign)
    salary = await category_id(session, a.default_space_id, "Salário", "income")
    with pytest.raises(DomainError, match="invalid_category"):
        await _tx(session, a, acc, 1_000, cat=salary)  # despesa com categoria de receita
    await _tx(session, a, acc, 1_000, type="income", cat=salary)


async def test_transfer_shape_rules(session):
    a = await make_user(session, "a@x.com")
    one = await make_account(session, a.default_space_id, name="Um")
    two = await make_account(session, a.default_space_id, name="Dois")
    with pytest.raises(DomainError, match="invalid_transfer"):
        await _tx(session, a, one, 100, type="transfer")  # sem destino
    with pytest.raises(DomainError, match="invalid_transfer"):
        await _tx(session, a, one, 100, type="transfer", counter=one)  # mesma conta
    with pytest.raises(DomainError, match="invalid_transfer"):
        await _tx(session, a, one, 100, type="expense", counter=two)  # destino em despesa
    with pytest.raises(DomainError, match="invalid_type"):
        await _tx(session, a, one, 100, type="goal_contribution")


async def test_list_transactions_filters_by_period_category_account(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    one = await make_account(session, sp, name="Um")
    two = await make_account(session, sp, name="Dois")
    mercado, transporte = (
        await category_id(session, sp),
        await category_id(session, sp, "Transporte"),
    )
    t1 = await _tx(session, a, one, 1_000, on=date(2026, 11, 1), cat=mercado)
    t2 = await _tx(session, a, one, 2_000, on=date(2026, 11, 15), cat=transporte)
    t3 = await _tx(session, a, two, 3_000, on=date(2026, 12, 2), cat=mercado)

    async def ids(**kw):
        return [t.id for t in await list_transactions(session, viewer_id=a.id, space_id=sp, **kw)]

    assert await ids() == [t3.id, t2.id, t1.id]  # mais recente primeiro
    assert await ids(start=date(2026, 11, 10), end=date(2026, 11, 30)) == [t2.id]
    assert await ids(category_id=mercado) == [t3.id, t1.id]
    assert await ids(account_id=one.id) == [t2.id, t1.id]
    assert await ids(account_id=two.id, category_id=transporte) == []
    assert await ids(limit=1, offset=1) == [t2.id]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mercado Extra Loja 123", "mercado extra"),
        ("PADARIA SÃO JOÃO #45", "padaria sao joao"),
        ("Uber *Trip 8821", "uber trip"),
        ("  Farmácia   Pague Menos  ", "farmacia pague menos"),
        ("Posto Shell Nº 7", "posto shell"),
        ("Açaí do Zé", "acai do ze"),
    ],
)
def test_normalize_merchant(raw, expected):
    assert normalize_merchant(raw) == expected

from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.accounts.statement import account_statement
from app.domain.spaces.service import remove_member
from app.domain.transactions.service import account_balance, create_transaction
from tests.factories import category_id, make_account, make_family, make_user

D = date(2026, 11, 10)
RANGE = (date(2026, 11, 1), date(2026, 11, 30))


async def _setup(session):
    """w e h na família; conta conjunta da família; w lança um item da família e um pessoal."""
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    acc = await make_account(session, fam.id, name="Conjunta", initial=50_000)
    shared = await create_transaction(
        session, actor_id=w.id, space_id=fam.id, type="expense", amount_cents=10_000,
        occurred_on=D, description="mercado", account_id=acc.id,
        category_id=await category_id(session, fam.id),
    )  # fmt: skip
    secret = await create_transaction(
        session, actor_id=w.id, space_id=w.default_space_id, type="expense", amount_cents=4_000,
        occurred_on=D, description="presente", account_id=acc.id,
        category_id=await category_id(session, w.default_space_id),
    )  # fmt: skip
    return w, h, fam, acc, shared, secret


async def test_private_items_aggregated_for_non_member_viewer(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    st = await account_statement(session, h.id, acc.id, *RANGE)
    assert [i.id for i in st.items] == [shared.id]  # só o item da família aparece
    assert st.items[0].amount_cents == -10_000
    assert st.private_total_cents == -4_000  # o pessoal da w vira agregado
    assert st.total_cents == -14_000  # o total fecha
    assert secret.id not in [i.id for i in st.items]
    assert await account_balance(session, acc.id) == 50_000 + st.total_cents


async def test_owner_sees_all_items(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    st = await account_statement(session, w.id, acc.id, *RANGE)
    assert {i.id for i in st.items} == {shared.id, secret.id}
    assert st.private_total_cents == 0 and st.total_cents == -14_000


async def test_statement_respects_period(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    st = await account_statement(session, w.id, acc.id, date(2026, 12, 1), date(2026, 12, 31))
    assert st.items == [] and st.private_total_cents == 0 and st.total_cents == 0


async def test_removed_member_loses_statement_access(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    await account_statement(session, h.id, acc.id, *RANGE)
    await remove_member(session, actor_id=w.id, space_id=fam.id, user_id=h.id)
    with pytest.raises(HTTPException) as e:
        await account_statement(session, h.id, acc.id, *RANGE)
    assert e.value.status_code == 404


async def test_statement_of_unrelated_account_is_404(session):
    w, h, fam, acc, shared, secret = await _setup(session)
    other = await make_user(session, "z@x.com")
    with pytest.raises(HTTPException) as e:
        await account_statement(session, other.id, acc.id, *RANGE)
    assert e.value.status_code == 404

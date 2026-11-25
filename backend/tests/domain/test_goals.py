from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.errors import DomainError
from app.domain.goals.service import (
    contribute,
    create_goal,
    goal_links,
    goal_progress,
    update_goal,
    visible_goal,
    withdraw,
)
from app.domain.pockets.service import create_pocket, deposit
from app.domain.transactions.service import account_balance
from tests.factories import make_account, make_family, make_user

D = date(2026, 1, 15)


async def _goal(session, user, *, target=120_000, deadline=None, created_on=D, space=None):
    return await create_goal(
        session, actor_id=user.id, space_id=space or user.default_space_id, name="Viagem",
        target_cents=target, deadline=deadline, created_on=created_on,
    )  # fmt: skip


async def test_contribution_reduces_source_balance(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    goal = await _goal(session, a)
    tx = await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=acc.id, amount_cents=25_000, on=D
    )  # fmt: skip
    assert tx.type == "transfer" and tx.goal_id == goal.id
    assert tx.account_id == acc.id and tx.counter_account_id is None
    assert tx.space_id == goal.space_id and tx.created_by == a.id
    assert await account_balance(session, acc.id) == 75_000
    assert (await goal_progress(session, goal.id, today=D)).saved == 25_000

    back = await withdraw(
        session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=5_000, on=D
    )  # fmt: skip
    assert back.account_id is None and back.counter_account_id == acc.id
    assert await account_balance(session, acc.id) == 80_000  # retirada devolve à conta
    assert (await goal_progress(session, goal.id, today=D)).saved == 20_000
    with pytest.raises(DomainError, match="insufficient_saved"):
        await withdraw(
            session, actor_id=a.id, goal_id=goal.id, to_account_id=acc.id, amount_cents=20_001,
            on=D,
        )  # fmt: skip


async def test_monthly_needed(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    g = await _goal(session, a, target=120_000, deadline=date(2026, 7, 15))
    p = await goal_progress(session, g.id, today=D)
    assert (p.saved, p.target, p.monthly_needed) == (0, 120_000, 20_000)  # 6 meses
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=30_000, on=D
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=D)).monthly_needed == 15_000
    g2 = await _goal(session, a, target=100_000, deadline=date(2026, 4, 15))
    # arredonda para cima: 100000 / 3 meses
    assert (await goal_progress(session, g2.id, today=D)).monthly_needed == 33_334
    g3 = await _goal(session, a, target=1_000, deadline=date(2026, 1, 10))
    assert (await goal_progress(session, g3.id, today=D)).monthly_needed == 1_000  # prazo vencido
    g4 = await _goal(session, a, target=1_000)
    p4 = await goal_progress(session, g4.id, today=D)
    assert p4.monthly_needed is None and p4.behind is False  # sem prazo


async def test_behind_flag(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    g = await _goal(
        session, a, target=30_000, created_on=date(2026, 1, 1), deadline=date(2026, 1, 31)
    )  # 30 dias; no dia 16 esperado = 15.000
    mid = date(2026, 1, 16)
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=10_000, on=mid
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=mid)).behind is True
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=5_000, on=mid
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=mid)).behind is False  # 15.000 não é < 15.000
    assert (await goal_progress(session, g.id, today=date(2026, 2, 5))).behind is True  # vencida
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=15_000, on=mid
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=date(2026, 2, 5))).behind is False  # concluída


async def test_goal_access_and_validation(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    mine = await make_account(session, a.default_space_id, initial=10_000)
    theirs = await make_account(session, b.default_space_id, initial=10_000)
    g = await _goal(session, a)
    with pytest.raises(HTTPException) as e:  # b não é membro do espaço da meta
        await contribute(
            session, actor_id=b.id, goal_id=g.id, from_account_id=theirs.id, amount_cents=100, on=D
        )  # fmt: skip
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await visible_goal(session, b.id, g.id)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:  # a debita de conta do b: 403
        await contribute(
            session, actor_id=a.id, goal_id=g.id, from_account_id=theirs.id, amount_cents=100, on=D
        )  # fmt: skip
    assert e.value.status_code == 403
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await contribute(
            session, actor_id=a.id, goal_id=g.id, from_account_id=mine.id, amount_cents=0, on=D
        )  # fmt: skip
    with pytest.raises(DomainError, match="amount_must_be_positive"):
        await _goal(session, a, target=0)


async def test_family_goal_funded_from_personal_account(session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    mine = await make_account(session, h.default_space_id, name="Do h", initial=50_000)
    g = await _goal(session, w, space=fam.id)
    tx = await contribute(
        session, actor_id=h.id, goal_id=g.id, from_account_id=mine.id, amount_cents=10_000, on=D
    )  # fmt: skip
    assert tx.space_id == fam.id and await account_balance(session, mine.id) == 40_000
    assert (await goal_progress(session, g.id, today=D)).saved == 10_000


async def test_concurrent_contributions_and_withdrawals(session):
    import asyncio

    from app.core.db import SessionLocal

    a = await make_user(session, "a@x.com")
    wallet = await make_account(session, a.default_space_id, type="wallet", initial=100_000)
    g = await _goal(session, a)

    async def run(fn, **kw):
        async with SessionLocal() as s:
            return await fn(s, actor_id=a.id, goal_id=g.id, amount_cents=1_000, on=D, **kw)

    await asyncio.gather(*[run(contribute, from_account_id=wallet.id) for _ in range(5)])
    assert (await goal_progress(session, g.id, today=D)).saved == 5_000
    assert await account_balance(session, wallet.id) == 95_000
    res = await asyncio.gather(
        *[run(withdraw, to_account_id=wallet.id) for _ in range(8)], return_exceptions=True
    )
    assert sum(isinstance(r, DomainError) for r in res) == 3  # nunca saca mais do que guardou
    assert (await goal_progress(session, g.id, today=D)).saved == 0


async def test_monthly_needed_edges(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    g = await _goal(session, a, target=1_000, deadline=date(2026, 7, 15))
    await contribute(
        session, actor_id=a.id, goal_id=g.id, from_account_id=acc.id, amount_cents=1_000, on=D
    )  # fmt: skip
    assert (await goal_progress(session, g.id, today=D)).monthly_needed == 0  # meta atingida
    g2 = await _goal(session, a, target=5_000, deadline=D)
    p2 = await goal_progress(session, g2.id, today=D)  # prazo hoje: falta tudo
    assert p2.monthly_needed == 5_000 and p2.behind is True  # criada no próprio prazo
    g3 = await _goal(session, a, target=5_000, deadline=D, created_on=D)
    assert (await goal_progress(session, g3.id, today=date(2026, 1, 14))).behind is False


async def test_goal_limits_at_service_level(session):
    import asyncio

    from app.core.db import SessionLocal
    from app.core.money import MAX_CENTS

    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    g = await _goal(session, a)
    aid, gid, accid = a.id, g.id, acc.id  # rollback expira os objetos
    with pytest.raises(DomainError, match="amount_too_large"):
        await _goal(session, a, target=MAX_CENTS + 1)
    for kw in ({"created_on": date(1999, 12, 31)}, {"created_on": date(2101, 1, 1)}):
        with pytest.raises(DomainError, match="invalid_date"):
            await _goal(session, a, **kw)
    for fn, key in ((contribute, "from_account_id"), (withdraw, "to_account_id")):
        base = {"actor_id": a.id, "goal_id": g.id, key: acc.id}
        with pytest.raises(DomainError, match="amount_too_large"):
            await fn(session, amount_cents=MAX_CENTS + 1, on=D, **base)
        for bad in (date(1999, 12, 31), date(2101, 1, 1)):
            with pytest.raises(DomainError, match="invalid_date"):
                await fn(session, amount_cents=100, on=bad, **base)

    # retirada rejeitada solta o lock da meta
    with pytest.raises(DomainError, match="insufficient_saved"):
        await withdraw(
            session, actor_id=aid, goal_id=gid, to_account_id=accid, amount_cents=100, on=D
        )  # fmt: skip

    async def other():
        async with SessionLocal() as s:
            await contribute(
                s, actor_id=aid, goal_id=gid, from_account_id=accid, amount_cents=500, on=D
            )  # fmt: skip
            return await withdraw(
                s, actor_id=aid, goal_id=gid, to_account_id=accid, amount_cents=500, on=D
            )  # fmt: skip

    await asyncio.wait_for(other(), 5)


async def _pocket(session, user, acc, name="Reserva"):
    return await create_pocket(
        session, actor_id=user.id, space_id=acc.space_id, account_id=acc.id, name=name, cdi_bp=10000
    )


async def test_progress_sums_linked_account_and_pocket(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc1 = await make_account(session, sp, initial=50_000)
    acc2 = await make_account(session, sp, initial=100_000)
    pk = await _pocket(session, a, acc2)
    await deposit(session, actor_id=a.id, pocket_id=pk.id, amount_cents=30_000, on=D)
    goal = await _goal(session, a)
    await update_goal(
        session, actor_id=a.id, goal_id=goal.id,
        fields={"account_ids": [acc1.id], "pocket_ids": [pk.id]},
    )  # fmt: skip
    # acc1 inteira + só a caixinha de acc2; o resto de acc2 não conta
    assert (await goal_progress(session, goal.id, today=D)).saved == 80_000


async def test_pocket_of_linked_account_not_counted_twice(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=100_000)
    pk = await _pocket(session, a, acc)
    await deposit(session, actor_id=a.id, pocket_id=pk.id, amount_cents=30_000, on=D)
    goal = await _goal(session, a)
    await update_goal(
        session, actor_id=a.id, goal_id=goal.id,
        fields={"account_ids": [acc.id], "pocket_ids": [pk.id]},
    )  # fmt: skip
    assert (await goal_progress(session, goal.id, today=D)).saved == 100_000


async def test_account_and_pocket_belong_to_one_goal(session):
    a = await make_user(session, "a@x.com")
    acc = await make_account(session, a.default_space_id, initial=1_000)
    other = await make_account(session, a.default_space_id, initial=1_000)
    pk = await _pocket(session, a, acc)
    g1, g2, g3 = await _goal(session, a), await _goal(session, a), await _goal(session, a)
    await update_goal(session, actor_id=a.id, goal_id=g1.id, fields={"account_ids": [acc.id]})
    with pytest.raises(DomainError, match="already_linked"):  # mesma conta
        await update_goal(session, actor_id=a.id, goal_id=g2.id, fields={"account_ids": [acc.id]})
    with pytest.raises(DomainError, match="already_linked"):  # caixinha de conta de outra meta
        await update_goal(session, actor_id=a.id, goal_id=g2.id, fields={"pocket_ids": [pk.id]})
    pk2 = await _pocket(session, a, other)
    await update_goal(session, actor_id=a.id, goal_id=g2.id, fields={"pocket_ids": [pk2.id]})
    with pytest.raises(DomainError, match="already_linked"):  # conta cuja caixinha está noutra meta
        await update_goal(session, actor_id=a.id, goal_id=g3.id, fields={"account_ids": [other.id]})


async def test_links_replace_and_require_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    mine = await make_account(session, a.default_space_id)
    theirs = await make_account(session, b.default_space_id)
    goal = await _goal(session, a)
    with pytest.raises(HTTPException) as e:
        await update_goal(
            session, actor_id=a.id, goal_id=goal.id, fields={"account_ids": [theirs.id]}
        )
    assert e.value.status_code == 403
    await update_goal(session, actor_id=a.id, goal_id=goal.id, fields={"account_ids": [mine.id]})
    await update_goal(session, actor_id=a.id, goal_id=goal.id, fields={"account_ids": []})
    assert await goal_links(session, goal.id) == ([], [])

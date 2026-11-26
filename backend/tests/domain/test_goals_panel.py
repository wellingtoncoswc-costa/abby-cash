from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.goals.panel import goal_panel
from app.domain.goals.service import contribute, create_goal, withdraw
from app.domain.pockets.service import create_pocket, deposit
from tests.factories import make_account, make_user

D = date(2026, 11, 10)


async def test_goal_panel_composition_and_history(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    src = await make_account(session, sp, name="Origem", initial=100_000)
    linked = await make_account(session, sp, name="Ligada", initial=50_000)
    pk = await create_pocket(
        session, actor_id=a.id, space_id=sp, account_id=linked.id, name="Reserva", cdi_bp=10000
    )
    await deposit(session, actor_id=a.id, pocket_id=pk.id, amount_cents=20_000, on=D)
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=500_000, created_on=D,
        account_ids=[linked.id], pocket_ids=[pk.id],
    )  # fmt: skip
    await contribute(
        session, actor_id=a.id, goal_id=goal.id, from_account_id=src.id, amount_cents=10_000, on=D
    )
    await withdraw(
        session, actor_id=a.id, goal_id=goal.id, to_account_id=src.id, amount_cents=2_000, on=D
    )
    p = await goal_panel(session, a.id, goal.id, today=D)
    assert p["direct_cents"] == 8_000
    assert [(x["name"], x["balance_cents"]) for x in p["accounts"]] == [("Ligada", 50_000)]
    # a caixinha da conta ligada já está no saldo da conta: aparece, mas não soma de novo
    assert [(x["name"], x["balance_cents"], x["counted"]) for x in p["pockets"]] == [
        ("Reserva", 20_000, False)
    ]
    assert p["total_cents"] == 58_000
    assert [(c["direction"], c["amount_cents"]) for c in p["contributions"]] == [
        ("out", 2_000),
        ("in", 10_000),
    ]  # mais recente primeiro


async def test_goal_panel_guards_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    goal = await create_goal(
        session, actor_id=a.id, space_id=a.default_space_id, name="G", target_cents=1_000,
        created_on=D,
    )  # fmt: skip
    with pytest.raises(HTTPException) as e:
        await goal_panel(session, b.id, goal.id, today=D)
    assert e.value.status_code in (403, 404)

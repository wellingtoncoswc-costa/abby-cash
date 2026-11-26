from datetime import date

import pytest
from fastapi import HTTPException

from app.domain.goals.service import create_goal
from app.domain.pockets.models import PocketMovement
from app.domain.pockets.panel import pocket_panel
from app.domain.pockets.service import create_pocket
from tests.factories import make_account, make_user

TODAY = date(2026, 11, 25)


async def test_pocket_panel_yield_by_month_and_goals(session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    acc = await make_account(session, sp, initial=100_000)
    pk = await create_pocket(
        session, actor_id=a.id, space_id=sp, account_id=acc.id, name="Reserva", cdi_bp=10000
    )
    for kind, cents, on in (
        ("accrual", 100, date(2026, 11, 10)),
        ("accrual", 50, date(2026, 11, 11)),
        ("accrual", 70, date(2026, 10, 10)),
        ("accrual", 5, date(2026, 3, 10)),  # fora da janela de 6 meses
        ("deposit", 9_000, date(2026, 11, 12)),  # não é rendimento
    ):
        session.add(
            PocketMovement(
                pocket_id=pk.id, kind=kind, amount_cents=cents, occurred_on=on,
                ref_date=on if kind == "accrual" else None,
            )
        )  # fmt: skip
    await session.commit()
    goal = await create_goal(
        session, actor_id=a.id, space_id=sp, name="Viagem", target_cents=1_000,
        created_on=TODAY, pocket_ids=[pk.id],
    )  # fmt: skip
    p = await pocket_panel(session, a.id, pk.id, today=TODAY)
    assert [(m["month"], m["yield_cents"]) for m in p["yield_by_month"]] == [
        (date(2026, 6, 1), 0), (date(2026, 7, 1), 0), (date(2026, 8, 1), 0),
        (date(2026, 9, 1), 0), (date(2026, 10, 1), 70), (date(2026, 11, 1), 150),
    ]  # fmt: skip
    assert [g["id"] for g in p["goals"]] == [goal.id]


async def test_pocket_panel_guards_access(session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    acc = await make_account(session, a.default_space_id)
    pk = await create_pocket(
        session, actor_id=a.id, space_id=a.default_space_id, account_id=acc.id, name="R",
        cdi_bp=10000,
    )  # fmt: skip
    with pytest.raises(HTTPException) as e:
        await pocket_panel(session, b.id, pk.id, today=TODAY)
    assert e.value.status_code in (403, 404)

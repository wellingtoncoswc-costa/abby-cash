from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import func, select

from app.channels import registry
from app.core.redis import redis
from app.domain.pockets.cdi import fetch_cdi
from app.domain.pockets.models import CdiRate, PocketMovement
from app.domain.pockets.service import create_pocket, deposit
from app.jobs.pockets import ALERT_KEY, FAIL_KEY, sync_cdi_job
from tests.assistant.fakes import FakeAdapter
from tests.factories import make_account, make_link, make_user

# resposta no formato real da SGS 12
SGS = [
    {"data": "24/11/2026", "valor": "0.055131"},
    {"data": "23/11/2026", "valor": "0.055131"},
]
TODAY = date(2026, 11, 25)  # quarta; último dia útil = terça 24


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_fetch_validates_format_and_sends_expected_request():
    seen = []

    def ok(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=SGS)

    rows = await fetch_cdi(date(2026, 11, 23), _transport(ok))
    assert [(r.data, str(r.valor)) for r in rows][0] == (date(2026, 11, 24), "0.055131")
    q = seen[0].url.params
    assert seen[0].url.host == "api.bcb.gov.br" and "bcdata.sgs.12" in seen[0].url.path
    assert (q["formato"], q["dataInicial"]) == ("json", "23/11/2026")
    bad = _transport(lambda r: httpx.Response(200, json=[{"data": "2026-11-24", "valor": "x"}]))
    with pytest.raises(ValueError):
        await fetch_cdi(date(2026, 11, 23), bad)
    redirect = _transport(lambda r: httpx.Response(302, headers={"location": "https://evil.test/"}))
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_cdi(date(2026, 11, 23), redirect)


async def test_job_fetches_cdi_and_accrues_idempotently(session):
    user = await make_user(session, "a@x.com")
    acc = await make_account(session, user.default_space_id, initial=100_000)
    p = await create_pocket(
        session,
        actor_id=user.id,
        space_id=user.default_space_id,
        account_id=acc.id,
        name="R",
        cdi_bp=10_000,
    )
    p.created_at = datetime(2026, 11, 20, 15, tzinfo=UTC)
    await session.commit()
    pid = p.id
    await deposit(
        session, actor_id=user.id, pocket_id=pid, amount_cents=100_000, on=date(2026, 11, 21)
    )
    calls = []

    def ok(req):
        calls.append(1)
        return httpx.Response(200, json=SGS)

    for _ in range(2):
        await sync_cdi_job({}, today=TODAY, transport=_transport(ok))
    assert len(calls) == 1  # já tem o último dia útil: não busca de novo
    assert await session.scalar(select(func.count()).select_from(CdiRate)) == 2
    rows = (
        await session.execute(
            select(PocketMovement.ref_date, PocketMovement.amount_cents)
            .where(PocketMovement.kind == "accrual")
            .order_by(PocketMovement.ref_date)
        )
    ).all()
    assert [tuple(r) for r in rows] == [(date(2026, 11, 23), 55), (date(2026, 11, 24), 55)]


async def test_three_failures_alert_admins_once(session, monkeypatch):
    tg = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "telegram", tg)
    admin = await make_user(session, "adm@x.com")
    admin.is_admin = True
    await session.commit()
    await make_link(session, admin, "999")
    boom = _transport(lambda r: httpx.Response(500))
    for _ in range(5):
        await sync_cdi_job({}, today=TODAY, transport=boom)
    assert len(tg.sent) == 1 and "CDI" in tg.sent[0][1]
    assert int(await redis.get(FAIL_KEY)) == 5
    await sync_cdi_job(
        {}, today=TODAY, transport=_transport(lambda r: httpx.Response(200, json=SGS))
    )
    assert await redis.get(FAIL_KEY) is None and await redis.get(ALERT_KEY) is None

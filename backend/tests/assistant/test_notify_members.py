import asyncio
import time

from app.assistant import notify
from app.assistant.notify import notify_members
from tests.factories import make_family, make_user


async def test_members_notified_concurrently_with_timeout(session, monkeypatch):
    a, b, c, d = [await make_user(session, f"{n}@x.com") for n in "abcd"]
    fam = await make_family(session, a, b, c, d)
    monkeypatch.setattr(notify, "SEND_TIMEOUT_S", 0.3)
    seen: list = []

    async def fake(uid, text):
        seen.append(uid)
        if uid == b.id:
            await asyncio.sleep(5)  # canal travado
        if uid == c.id:
            raise RuntimeError("x")
        await asyncio.sleep(0.2)

    monkeypatch.setattr(notify, "notify_user", fake)
    t0 = time.monotonic()
    await notify_members(session, fam.id, a.id, "alerta")
    assert time.monotonic() - t0 < 1  # paralelo (3x0.2 serial seria 0.6+) e com teto
    assert set(seen) == {b.id, c.id, d.id}

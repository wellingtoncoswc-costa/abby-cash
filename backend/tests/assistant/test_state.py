from datetime import timedelta

from app.assistant.state import clear_state, get_state, set_state
from tests.factories import TS, make_user


async def test_state_roundtrip_expiry_and_clear(session):
    ana = await make_user(session, "ana@x.com")
    await set_state(session, ana.id, "telegram", "amount", {"a": 1}, TS)
    st = await get_state(session, ana.id, "telegram", TS + timedelta(minutes=29))
    assert st is not None and st.kind == "amount" and st.data == {"a": 1}
    await set_state(session, ana.id, "telegram", "confirm", {}, TS)  # substitui, não duplica
    assert (await get_state(session, ana.id, "telegram", TS)).kind == "confirm"
    assert await get_state(session, ana.id, "telegram", TS + timedelta(minutes=30)) is None
    assert await get_state(session, ana.id, "telegram", TS) is None  # expirado foi apagado
    await set_state(session, ana.id, "telegram", "amount", {}, TS)
    await clear_state(session, ana.id, "telegram")
    assert await get_state(session, ana.id, "telegram", TS) is None

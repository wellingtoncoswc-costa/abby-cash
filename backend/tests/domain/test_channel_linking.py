import asyncio

import pytest
from sqlalchemy import select

from app.core.redis import redis
from app.domain.channels.linking import (
    create_link_code,
    find_user_by_link,
    link_with_code,
    unlink,
)
from app.domain.channels.models import ChannelLink
from app.domain.errors import DomainError
from tests.factories import make_user


async def _links(session) -> list[ChannelLink]:
    return list(await session.scalars(select(ChannelLink)))


async def test_link_with_code(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    assert len(code) == 6 and code.isdigit()
    user = await link_with_code(session, channel="telegram", external_user_id="111", code=code)
    assert user is not None and user.id == ana.id
    assert [
        (link.user_id, link.channel, link.external_user_id) for link in await _links(session)
    ] == [(ana.id, "telegram", "111")]
    found = await find_user_by_link(session, "telegram", "111")
    assert found is not None and found.id == ana.id
    assert found.preferred_channel == "telegram"
    assert await find_user_by_link(session, "telegram", "999") is None
    # uso único
    again = await link_with_code(session, channel="telegram", external_user_id="222", code=code)
    assert again is None and len(await _links(session)) == 1


async def test_expired_code_rejected(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    await redis.pexpire(f"linkcode:{code}", 1)
    await asyncio.sleep(0.05)
    assert (
        await link_with_code(session, channel="telegram", external_user_id="111", code=code) is None
    )
    assert await _links(session) == []


async def test_code_is_bound_to_channel(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    got = await link_with_code(
        session, channel="whatsapp_evolution", external_user_id="1", code=code
    )
    assert got is None and await _links(session) == []


async def test_attempts_are_limited_per_sender(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    wrong = "000000" if code != "000000" else "000001"
    for _ in range(10):
        assert (
            await link_with_code(session, channel="telegram", external_user_id="9", code=wrong)
            is None
        )
    with pytest.raises(DomainError, match="too_many_attempts"):  # nem o código certo passa
        await link_with_code(session, channel="telegram", external_user_id="9", code=code)
    assert await _links(session) == []
    # outro remetente não é afetado
    assert await link_with_code(session, channel="telegram", external_user_id="8", code=code)


async def test_code_dies_after_five_wrong_channel_tries(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    for i in range(5):
        await link_with_code(session, channel="x", external_user_id=str(i), code=code)
    assert await redis.get(f"linkcode:{code}") is None


async def test_external_id_cannot_be_linked_to_two_users(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    c1 = await create_link_code(ana.id, "telegram")
    await link_with_code(session, channel="telegram", external_user_id="111", code=c1)
    c2 = await create_link_code(bia.id, "telegram")
    with pytest.raises(DomainError, match="already_linked"):
        await link_with_code(session, channel="telegram", external_user_id="111", code=c2)
    assert len(await _links(session)) == 1


async def test_relink_replaces_external_id_and_unlink_removes(session):
    ana = await make_user(session, "ana@x.com")
    await link_with_code(
        session, channel="telegram", external_user_id="111",
        code=await create_link_code(ana.id, "telegram"),
    )  # fmt: skip
    await link_with_code(
        session, channel="telegram", external_user_id="222",
        code=await create_link_code(ana.id, "telegram"),
    )  # fmt: skip
    assert [link.external_user_id for link in await _links(session)] == ["222"]
    await unlink(session, ana.id, "telegram")
    assert await _links(session) == []

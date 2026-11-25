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


async def test_wrong_channel_code_is_not_consumed_and_looks_like_nonexistent(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    for i in range(8):
        assert (
            await link_with_code(session, channel="x", external_user_id=str(i), code=code) is None
        )
    assert await redis.get(f"linkcode:{code}") is not None  # atacante não queima o código
    missing = "000000" if code != "000000" else "000001"
    assert await link_with_code(session, channel="x", external_user_id="1", code=missing) is None


async def test_global_limit_blocks_valid_code_after_many_senders_fail(session):
    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")
    wrong = "000000" if code != "000000" else "000001"
    for i in range(30):  # cada remetente erra uma vez: o limite por remetente nunca dispara
        await link_with_code(session, channel="telegram", external_user_id=f"s{i}", code=wrong)
    assert (
        await link_with_code(session, channel="telegram", external_user_id="legit", code=code)
        is None
    )
    assert await redis.get(f"linkcode:{code}") is not None  # nem foi consumido
    assert await _links(session) == []
    assert await redis.ttl("link_fails:global") > 0


async def test_second_code_invalidates_first(session):
    ana = await make_user(session, "ana@x.com")
    c1 = await create_link_code(ana.id, "telegram")
    c2 = await create_link_code(ana.id, "telegram")
    assert await link_with_code(session, channel="telegram", external_user_id="1", code=c1) is None
    assert await link_with_code(session, channel="telegram", external_user_id="1", code=c2)


async def test_concurrent_double_use_links_once(session):
    from app.core.db import SessionLocal

    ana = await make_user(session, "ana@x.com")
    code = await create_link_code(ana.id, "telegram")

    async def use(ext: str):
        async with SessionLocal() as s:
            try:
                return await link_with_code(s, channel="telegram", external_user_id=ext, code=code)
            except DomainError:
                return None

    res = await asyncio.gather(*(use(str(i)) for i in range(5)))
    assert sum(r is not None for r in res) == 1
    assert len(await _links(session)) == 1


async def test_counters_always_have_ttl(session):
    from app.core.redis import incr_ttl

    await redis.set("k", 5)  # chave pré-existente sem TTL é consertada
    await incr_ttl("k", 100)
    assert await redis.ttl("k") > 0


async def test_unlink_resets_preferred_channel(session):
    ana = await make_user(session, "ana@x.com")
    await link_with_code(
        session, channel="telegram", external_user_id="1",
        code=await create_link_code(ana.id, "telegram"),
    )  # fmt: skip
    assert ana.preferred_channel == "telegram"
    session.add(ChannelLink(user_id=ana.id, channel="whatsapp_evolution", external_user_id="5"))
    await session.commit()
    await unlink(session, ana.id, "telegram")
    await session.refresh(ana)
    assert ana.preferred_channel == "whatsapp_evolution"
    await unlink(session, ana.id, "whatsapp_evolution")
    await session.refresh(ana)
    assert ana.preferred_channel is None


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

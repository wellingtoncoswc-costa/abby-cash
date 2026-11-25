from datetime import date

import pytest
from fastapi import HTTPException

from app.assistant.context import load_space_context
from tests.factories import make_account, make_card, make_family, make_user

TODAY = date(2026, 11, 25)


async def ctx(session, user, space_id):
    return await load_space_context(
        session, user_id=user.id, space_id=space_id, today=TODAY, tz=user.tz
    )


async def test_non_member_cannot_load_a_space_context(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    with pytest.raises(HTTPException) as e:
        await ctx(session, bia, ana.default_space_id)
    assert e.value.status_code == 404


async def test_context_lists_only_what_the_user_may_use(session):
    ana, bia = await make_user(session, "ana@x.com"), await make_user(session, "bia@x.com")
    fam = await make_family(session, ana, bia)
    await make_account(session, fam.id, name="Conta Casa")
    await make_account(session, ana.default_space_id, name="Segredo da Ana")
    await make_card(session, ana, fam.id, name="Visa Casa")
    c = await ctx(session, bia, fam.id)
    assert c.space_id == fam.id and c.space_name == "Casa"
    assert {a.name for a in c.accounts} == {"Carteira", "Conta Casa"}  # a da Ana não aparece
    assert [x.name for x in c.cards] == ["Visa Casa"]
    assert "Mercado" in {x.name for x in c.categories if x.kind == "expense"}
    assert c.default_account_id is None  # a Bia ainda não escolheu conta padrão na família
    own = await ctx(session, bia, bia.default_space_id)
    assert own.default_account_id is not None  # carteira
    assert {a.name for a in own.accounts} == {"Carteira", "Conta Casa"}  # contas da família valem

from sqlalchemy import select

from app.ai.models import AiUsage
from app.core.config import get_settings
from app.domain.spaces.models import SpaceMember
from tests.assistant.fakes import expense


async def test_message_rate_limit_replies_once_without_llm(ana, parser, monkeypatch):
    monkeypatch.setattr(get_settings(), "MSG_RATE_PER_HOUR", 2)
    assert await ana.say("ajuda")
    assert await ana.say("ajuda")
    assert "Muitas mensagens" in await ana.say("ajuda")
    assert await ana.say("ajuda") == "" and parser.calls == []


async def test_daily_token_budget_skips_llm_but_shortcuts_work(ana, parser, session, monkeypatch):
    sid = await session.scalar(
        select(SpaceMember.space_id).where(SpaceMember.user_id == ana.user.id)
    )
    session.add(AiUsage(space_id=sid, kind="intent", input_tokens=150, output_tokens=60))
    await session.commit()
    monkeypatch.setattr(get_settings(), "AI_DAILY_TOKEN_BUDGET", 200)
    parser.add(expense(4500, "Alimentação"))
    await ana.say("gastei 45 mercado")
    await ana.say("sim")
    assert "limite diário" in await ana.say("outros")
    assert parser.calls == []
    assert "limite" not in await ana.say("ajuda")

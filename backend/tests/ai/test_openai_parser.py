from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai.models import AiUsage
from app.ai.openai_parser import IntentParseError, OpenAIIntentParser, build_system_prompt
from app.ai.usage import record_ai_usage
from app.assistant.context import load_space_context
from app.assistant.intents import ParsedIntent
from app.core.config import get_settings
from tests.factories import make_user

TODAY = date(2026, 11, 25)


USAGE = SimpleNamespace(prompt_tokens=120, completion_tokens=30)


class FakeCompletions:
    def __init__(self, parsed, refusal=None):
        self.kwargs: dict = {}
        self._msg = SimpleNamespace(parsed=parsed, refusal=refusal)

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self._msg)], usage=USAGE)


def client_with(completions: FakeCompletions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


async def ctx_for(session):
    user = await make_user(session, "ana@x.com")
    ctx = await load_space_context(
        session, user_id=user.id, space_id=user.default_space_id, today=TODAY, tz=user.tz
    )
    return user, ctx


async def test_parse_sends_structured_request_and_returns_parsed(session):
    _, ctx = await ctx_for(session)
    want = ParsedIntent.of("lancar_despesa", amount_cents=4500, category_name="Mercado")
    comp = FakeCompletions(want)
    got = await OpenAIIntentParser(client=client_with(comp)).parse("gastei 45 no mercado", ctx)
    assert got == want
    kw = comp.kwargs
    assert kw["model"] == get_settings().AI_MODEL
    assert kw["response_format"] is ParsedIntent
    system, user_msg = kw["messages"]
    assert system["role"] == "system" and user_msg["role"] == "user"
    assert "Mercado" in system["content"] and "Carteira" in system["content"]
    assert "25/11/2026" not in system["content"]  # a data fica fora do prefixo estável
    assert "25/11/2026" in user_msg["content"] and "quarta" in user_msg["content"]
    assert user_msg["content"].endswith("gastei 45 no mercado")


async def test_parse_records_usage_for_the_space(session):
    user, ctx = await ctx_for(session)
    parser = OpenAIIntentParser(client=client_with(FakeCompletions(ParsedIntent.of("ajuda"))))
    await parser.parse("ajuda", ctx)
    row = await session.scalar(select(AiUsage))
    assert row is not None
    assert (row.space_id, row.kind, row.input_tokens, row.output_tokens) == (
        user.default_space_id, "intent", 120, 30,
    )  # fmt: skip


async def test_refusal_or_empty_response_raises(session):
    _, ctx = await ctx_for(session)
    parser = OpenAIIntentParser(client=client_with(FakeCompletions(None, refusal="não posso")))
    with pytest.raises(IntentParseError, match="não posso"):
        await parser.parse("x", ctx)


async def test_model_can_be_overridden_and_defaults_to_settings():
    assert OpenAIIntentParser(client=object(), model="gpt-x").model == "gpt-x"
    assert OpenAIIntentParser(client=object()).model == get_settings().AI_MODEL


async def test_prompt_lists_space_data_and_learned_rules(session):
    _, ctx = await ctx_for(session)
    from dataclasses import replace

    prompt = build_system_prompt(replace(ctx, rules=[("padaria pao quente", "Alimentação")]))
    assert "Categorias de despesa:" in prompt and "Impostos e taxas" in prompt
    assert "Categorias de receita:" in prompt and "Salário" in prompt
    assert "padaria pao quente -> Alimentação" in prompt
    assert "Cartões: (nenhum)" in prompt
    assert "@" not in prompt  # nada de e-mail/identificadores do usuário


async def test_record_ai_usage_never_raises(session):
    from uuid import uuid4

    await record_ai_usage(
        uuid4(), "intent", input_tokens=1
    )  # espaço inexistente: FK falha, só loga
    assert await session.scalar(select(AiUsage)) is None


async def test_missing_api_key_fails_at_parse_time_not_at_construction(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    parser = OpenAIIntentParser()  # nunca levanta: o worker sobe mesmo sem chave
    _, ctx = await ctx_for(session)
    with pytest.raises(Exception, match="credentials"):
        await parser.parse("oi", ctx)


async def test_overlong_message_is_rejected_before_calling_the_api(session):
    _, ctx = await ctx_for(session)
    comp = FakeCompletions(ParsedIntent.of("ajuda"))
    with pytest.raises(IntentParseError, match="too_long"):
        await OpenAIIntentParser(client=client_with(comp)).parse("a" * 2001, ctx)
    assert comp.kwargs == {}


async def test_prompt_marks_user_text_as_untrusted_data(session):
    _, ctx = await ctx_for(session)
    assert "dados não confiáveis" in build_system_prompt(ctx)

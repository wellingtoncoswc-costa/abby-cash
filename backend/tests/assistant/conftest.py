import pytest

from app.channels import registry
from app.jobs.inbound import process_inbound
from tests.assistant.fakes import FakeAdapter, FakeParser
from tests.factories import TS, make_inbound, make_link, make_user


@pytest.fixture
def adapter(monkeypatch) -> FakeAdapter:
    fake = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "telegram", fake)
    return fake


@pytest.fixture
def parser() -> FakeParser:
    return FakeParser()


class Chat:
    """Uma pessoa conversando com o bot: `say` entrega a mensagem ao worker e devolve a resposta."""

    def __init__(self, session, user, adapter, parser, ext) -> None:
        self.session, self.user, self.adapter, self.parser, self.ext = (
            session, user, adapter, parser, ext,
        )  # fmt: skip
        self.n = 0

    async def say(self, text: str, *, ts=TS, media_kind: str | None = None) -> str:
        self.n += 1
        iid = await make_inbound(
            self.session, text, ext=self.ext, msg_id=self.n, ts=ts, media_kind=media_kind
        )
        before = len(self.adapter.sent)
        await process_inbound({"parser": self.parser}, str(iid))
        return "\n".join(t for e, t in self.adapter.sent[before:] if e == self.ext)


@pytest.fixture
def new_chat(session, adapter, parser):
    async def make(email: str = "ana@x.com", ext: str = "111") -> Chat:
        user = await make_user(session, email)
        await make_link(session, user, ext)
        return Chat(session, user, adapter, parser, ext)

    return make


@pytest.fixture
async def ana(new_chat) -> Chat:
    return await new_chat()

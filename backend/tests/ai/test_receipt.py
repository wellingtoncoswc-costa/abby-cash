import base64
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.ai.models import AiUsage
from app.ai.receipt import OpenAIReceiptReader, ReceiptData, ReceiptError
from app.domain.attachments import sniff_image
from tests.factories import make_user


class FakeCompletions:
    def __init__(self, parsed=None, error=None):
        self.parsed, self.error, self.kwargs = parsed, error, {}

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        usage = SimpleNamespace(prompt_tokens=900, completion_tokens=40)
        msg = SimpleNamespace(parsed=self.parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def reader(c: FakeCompletions) -> OpenAIReceiptReader:
    return OpenAIReceiptReader(SimpleNamespace(chat=SimpleNamespace(completions=c)), "gpt-4.1")


async def test_reader_sends_only_the_image_and_records_usage(session):
    user = await make_user(session, "ana@x.com")
    data = ReceiptData(confidence=0.9, amount_cents=100)
    c = FakeCompletions(data)
    out = await reader(c).read(b"IMG", "image/png", user.default_space_id)
    assert out is data and c.kwargs["response_format"] is ReceiptData
    [_, msg] = c.kwargs["messages"]
    assert msg["content"] == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(b"IMG").decode()},
        }
    ]
    usage = await session.scalar(select(AiUsage).where(AiUsage.kind == "receipt"))
    assert usage is not None and usage.input_tokens == 900


async def test_reader_wraps_sdk_errors_without_leaking():
    with pytest.raises(ReceiptError) as e:
        await reader(FakeCompletions(error=RuntimeError("secret body"))).read(b"I", "image/png")
    assert "secret" not in str(e.value) and e.value.__cause__ is None
    with pytest.raises(ReceiptError):
        await reader(FakeCompletions(None)).read(b"I", "image/png")


@pytest.mark.parametrize("kw", [{"amount_cents": 0}, {"amount_cents": 10**11}, {"confidence": 2}])
def test_receipt_data_bounds(kw):
    with pytest.raises(ValidationError):
        ReceiptData(**{"confidence": 0.5, **kw})


def test_sniff_ignores_everything_but_magic_bytes():
    assert sniff_image(b"\xff\xd8\xff\xe0x") == "image/jpeg"
    assert sniff_image(b"\x89PNG\r\n\x1a\nx") == "image/png"
    assert sniff_image(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert sniff_image(b"GIF89a") is None and sniff_image(b"<svg>") is None

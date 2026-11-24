import httpx
import pytest

from app.ai.stt import HttpWhisperTranscriber, SttError
from app.core.config import get_settings


def make(handler):
    return HttpWhisperTranscriber(
        "http://stt:8000", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_transcribe_posts_multipart_and_parses():
    def handler(r: httpx.Request) -> httpx.Response:
        assert r.url.path == "/transcribe" and b"AUDIO" in r.content
        return httpx.Response(200, json={"text": " oi mundo ", "duration_s": 2.5})

    out = await make(handler).transcribe(b"AUDIO", "audio/ogg")
    assert (out.text, out.duration_s) == ("oi mundo", 2.5)


@pytest.mark.parametrize(
    "resp",
    [httpx.Response(413), httpx.Response(200, json={"x": 1}), httpx.Response(200, text="no")],
)
async def test_transcribe_errors_are_wrapped(resp):
    with pytest.raises(SttError) as e:
        await make(lambda r: resp).transcribe(b"A", "audio/ogg")
    assert "stt" not in str(e.value) and e.value.__cause__ is None


@pytest.mark.slow
async def test_real_stt_service_if_reachable():  # precisa do serviço e de um áudio curto real
    import pathlib

    sample = pathlib.Path(__file__).parents[1] / "fixtures" / "sample_pt.ogg"
    url = get_settings().STT_URL
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            await c.get(f"{url}/health")
    except httpx.HTTPError:
        pytest.skip("STT_URL inalcançável")
    if not sample.exists():
        pytest.skip("tests/fixtures/sample_pt.ogg ausente")
    out = await HttpWhisperTranscriber().transcribe(sample.read_bytes(), "audio/ogg")
    assert out.text and out.duration_s > 0

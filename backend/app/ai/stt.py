from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import get_settings


class SttError(Exception):
    """Falha do serviço de transcrição. Nunca carrega URL, corpo nem áudio."""


@dataclass
class Transcript:
    text: str
    duration_s: float


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime: str) -> Transcript: ...


class HttpWhisperTranscriber:
    def __init__(self, url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._url = (url or get_settings().STT_URL).rstrip("/")
        # CPU: áudio de 3 min leva um bom tempo; connect curto, read longo
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))

    async def transcribe(self, audio: bytes, mime: str) -> Transcript:
        try:
            r = await self._client.post(
                f"{self._url}/transcribe", files={"file": ("audio", audio, mime)}
            )
            r.raise_for_status()
            data: Any = r.json()
            return Transcript(str(data["text"]).strip(), float(data["duration_s"]))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            raise SttError(type(e).__name__) from None

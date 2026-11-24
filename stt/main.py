"""STT interno (faster-whisper, CPU int8). Sem autenticação: só a rede do Compose enxerga."""

import os
import tempfile

from fastapi import FastAPI, HTTPException, UploadFile

MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 180
app = FastAPI()
_model = None


def model():  # carrega no primeiro uso (o 1º start baixa o modelo para o volume)
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        name = os.environ.get("STT_MODEL", "small")
        _model = WhisperModel(name, device="cpu", compute_type="int8")
    return _model


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/transcribe")
def transcribe(file: UploadFile) -> dict[str, object]:  # def: roda no threadpool, não trava o loop
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "audio too large")
    with tempfile.NamedTemporaryFile() as f:  # ffmpeg (via PyAV) lê ogg/opus do arquivo
        f.write(data)
        f.flush()
        segments, info = model().transcribe(f.name, language="pt", vad_filter=True)
        if info.duration > MAX_SECONDS:
            raise HTTPException(413, "audio too long")
        text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "duration_s": info.duration}

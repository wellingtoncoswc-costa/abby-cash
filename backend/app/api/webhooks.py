from fastapi import APIRouter, HTTPException, Request

from app.api.deps import Session
from app.channels.ingest import ingest
from app.channels.registry import get_adapter
from app.jobs.queue import enqueue_inbound

MAX_BODY = 1_000_000  # updates do Telegram são pequenos; recusa antes de parsear

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/{channel}")
async def webhook(channel: str, request: Request, session: Session) -> dict[str, bool]:
    try:
        adapter = get_adapter(channel)
    except KeyError:
        raise HTTPException(404, "unknown_channel") from None
    if not adapter.verify(request):
        raise HTTPException(401, "invalid_secret")
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise HTTPException(413, "payload_too_large")
    if len(await request.body()) > MAX_BODY:  # sem Content-Length (chunked) ou mentiroso
        raise HTTPException(413, "payload_too_large")
    try:
        msgs = await adapter.parse_webhook(request)
    except ValueError:  # JSON inválido ou payload fora do formato
        raise HTTPException(400, "bad_payload") from None
    await ingest(session, msgs, enqueue_inbound)  # só grava e enfileira; o worker processa
    return {"ok": True}

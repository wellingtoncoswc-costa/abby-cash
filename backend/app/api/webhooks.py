from fastapi import APIRouter, HTTPException, Request

from app.api.deps import Session, rate_limit
from app.channels.ingest import ingest
from app.channels.registry import get_adapter
from app.core.config import get_settings
from app.core.http import client_ip
from app.jobs.queue import enqueue_inbound

MAX_BODY = 1_000_000  # updates do Telegram são pequenos; recusa antes de parsear

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/{channel}")
async def webhook(channel: str, request: Request, session: Session) -> dict[str, bool]:
    await rate_limit(f"webhook_ip:{client_ip(request)}", get_settings().WEBHOOK_RATE_PER_MIN, 60)
    try:
        adapter = get_adapter(channel)
    except KeyError:
        raise HTTPException(404, "unknown_channel") from None
    if not adapter.verify(request):
        raise HTTPException(401, "invalid_secret")
    declared = request.headers.get("content-length") or "0"
    if not declared.isascii() or not declared.isdigit():
        raise HTTPException(400, "bad_content_length")
    if int(declared) > MAX_BODY:
        raise HTTPException(413, "payload_too_large")
    if len(await request.body()) > MAX_BODY:  # sem Content-Length (chunked) ou mentiroso
        raise HTTPException(413, "payload_too_large")
    try:
        msgs = await adapter.parse_webhook(request)
    except ValueError:  # JSON inválido ou payload fora do formato
        raise HTTPException(400, "bad_payload") from None
    await ingest(session, msgs, enqueue_inbound)  # só grava e enfileira; o worker processa
    return {"ok": True}

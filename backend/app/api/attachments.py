from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, Session
from app.core.config import get_settings
from app.domain.attachments import Attachment, read_file, sniff_image
from app.domain.spaces.access import require_member

router = APIRouter(tags=["attachments"])


@router.get("/attachments/{attachment_id}", response_class=Response)
async def get_attachment(attachment_id: UUID, user: CurrentUser, session: Session) -> Response:
    att = await session.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(404, "not_found")
    await require_member(session, user.id, att.space_id)  # não-membro: 404 igual a inexistente
    root = Path(get_settings().STORAGE_DIR).resolve()
    if not (root / att.path).resolve().is_relative_to(root):
        raise HTTPException(404, "not_found")
    try:
        data = read_file(att)
    except OSError:
        raise HTTPException(404, "not_found") from None
    mime = sniff_image(data)  # tipo pelo conteúdo, nunca pelo banco
    if mime is None:
        raise HTTPException(404, "not_found")
    return Response(data, media_type=mime, headers={
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })  # fmt: skip

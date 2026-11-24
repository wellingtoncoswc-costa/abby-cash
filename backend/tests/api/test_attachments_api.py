import pytest

from app.core.config import get_settings
from app.domain.attachments import save_image
from tests.factories import auth, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "STORAGE_DIR", str(tmp_path))


async def test_member_reads_receipt_others_get_404(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    att = await save_image(
        session, space_id=a.default_space_id, origin="t", source_message_id="1", data=PNG
    )
    r = await client.get(f"/attachments/{att.id}", headers=auth(a))
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == "inline"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"
    for h in (auth(b), {}):
        assert (await client.get(f"/attachments/{att.id}", headers=h)).status_code in (404, 401)
    assert (await client.get(f"/attachments/{att.id}", headers=auth(b))).status_code == 404
    unknown = "00000000-0000-0000-0000-000000000001"
    assert (await client.get(f"/attachments/{unknown}", headers=auth(a))).status_code == 404

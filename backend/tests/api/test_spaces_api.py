from sqlalchemy import select

from app.domain.users.models import User
from app.domain.users.service import create_admin, create_signup_invite

PWD = "correct horse battery"


async def _login(client, session, email) -> dict[str, str]:
    admin = await create_admin(session, email=f"adm-{email}", name="Adm", password=PWD)
    code = (await create_signup_invite(session, created_by=admin.id)).code
    await client.post(
        "/auth/register",
        json={"email": email, "name": "U", "password": PWD, "invite_code": code},
    )
    r = await client.post("/auth/login", json={"email": email, "password": PWD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_space_isolation_over_http(client, session):
    ha = await _login(client, session, "a@x.com")
    hb = await _login(client, session, "b@x.com")
    fam = (await client.post("/spaces/family", json={"name": "Casa"}, headers=ha)).json()["id"]
    assert (await client.post("/spaces/family", json={"name": "X"}, headers=ha)).status_code == 409
    assert (await client.post(f"/spaces/{fam}/invites", headers=hb)).status_code == 404

    link = (await client.post(f"/spaces/{fam}/invites", headers=ha)).json()["link"]
    token = link.rsplit("/", 1)[1]
    assert (await client.post(f"/spaces/invites/{token}/accept", headers=hb)).status_code == 200
    assert (await client.post(f"/spaces/invites/{token}/accept", headers=hb)).status_code == 404
    assert fam in [s["id"] for s in (await client.get("/spaces", headers=hb)).json()]

    b_id = await session.scalar(select(User.id).where(User.email == "b@x.com"))
    assert (await client.delete(f"/spaces/{fam}/members/{b_id}", headers=hb)).status_code == 403
    assert (await client.delete(f"/spaces/{fam}/members/{b_id}", headers=ha)).status_code == 204
    assert fam not in [s["id"] for s in (await client.get("/spaces", headers=hb)).json()]
    assert (await client.post(f"/spaces/{fam}/invites", headers=hb)).status_code == 404

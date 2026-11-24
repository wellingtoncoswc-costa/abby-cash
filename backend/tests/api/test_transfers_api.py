import csv
import io
import json
import zipfile

from tests.factories import PWD, auth, make_account, make_family, make_user


async def _transfer(client, user, space, src, dst, amount=30_000, **extra):
    return await client.post(
        f"/spaces/{space}/transactions", headers=auth(user),
        json={"type": "transfer", "amount_cents": amount, "occurred_on": "2026-11-10",
              "account_id": str(src.id), "counter_account_id": str(dst.id), **extra},
    )  # fmt: skip


async def _acc(client, user, acc):
    return (await client.get(f"/accounts/{acc.id}", headers=auth(user))).json()


async def test_transfer_moves_both_balances_and_delete_reverts(client, session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    src = await make_account(session, sp, name="Nubank", initial=100_000)
    dst = await make_account(session, sp, name="Itaú", initial=5_000)
    r = await _transfer(client, a, sp, src, dst)
    assert r.status_code == 201 and r.json()["type"] == "transfer"
    assert (await _acc(client, a, src))["balance_cents"] == 70_000
    assert (await _acc(client, a, dst))["balance_cents"] == 35_000
    for acc, signed in ((src, -30_000), (dst, 30_000)):  # extrato das duas contas
        url = f"/accounts/{acc.id}/statement?start=2026-11-01&end=2026-11-30"
        items = (await client.get(url, headers=auth(a))).json()["items"]
        assert [(i["type"], i["amount_cents"]) for i in items] == [("transfer", signed)]
    # PATCH não edita transferência; nada muda
    p = await client.patch(f"/transactions/{r.json()['id']}", headers=auth(a),
                           json={"amount_cents": 1})  # fmt: skip
    assert p.status_code == 422 and p.json() == {"detail": "not_editable"}
    assert (await _acc(client, a, src))["balance_cents"] == 70_000
    assert (
        await client.delete(f"/transactions/{r.json()['id']}", headers=auth(a))
    ).status_code == 204
    assert (await _acc(client, a, src))["balance_cents"] == 100_000
    assert (await _acc(client, a, dst))["balance_cents"] == 5_000


async def test_same_account_and_bad_amounts_are_422(client, session):
    a = await make_user(session, "a@x.com")
    sp = a.default_space_id
    src = await make_account(session, sp, initial=10_000)
    r = await _transfer(client, a, sp, src, src)
    assert r.status_code == 422 and r.json() == {"detail": "invalid_transfer"}
    other = await make_account(session, sp, name="Outra")
    for bad in (0, -5, 10**12 + 1):
        assert (await _transfer(client, a, sp, src, other, bad)).status_code == 422
    assert (await _transfer(client, a, sp, src, other, 10**12)).status_code == 201  # sem caixinhas


async def test_other_users_account_is_refused(client, session):
    a, b = await make_user(session, "a@x.com"), await make_user(session, "b@x.com")
    mine = await make_account(session, a.default_space_id, name="Minha")
    theirs = await make_account(session, b.default_space_id, name="Dele")
    r = await _transfer(client, a, a.default_space_id, mine, theirs)  # destino alheio
    assert r.status_code == 403
    r = await _transfer(client, a, a.default_space_id, theirs, mine)  # origem alheia
    assert r.status_code == 403
    r = await _transfer(client, a, b.default_space_id, mine, theirs)  # espaço alheio
    assert r.status_code == 404


async def test_between_spaces_belongs_to_source_space_and_statement_privacy(client, session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, w, h)
    pessoal = await make_account(session, w.default_space_id, name="Pessoal", initial=50_000)
    conjunta = await make_account(session, fam.id, name="Conjunta")
    r = await _transfer(client, w, w.default_space_id, pessoal, conjunta, 20_000)
    assert r.status_code == 201 and r.json()["space_id"] == str(w.default_space_id)
    assert (await _acc(client, w, pessoal))["balance_cents"] == 30_000
    assert (await _acc(client, h, conjunta))["balance_cents"] == 20_000
    url = f"/accounts/{conjunta.id}/statement?start=2026-11-01&end=2026-11-30"
    seen = (await client.get(url, headers=auth(h))).json()  # h não é membro do espaço pessoal
    assert seen["items"] == [] and seen["private_total_cents"] == 20_000
    assert len((await client.get(url, headers=auth(w))).json()["items"]) == 1
    # h não pode sair da conta pessoal de w
    assert (await _transfer(client, h, fam.id, pessoal, conjunta)).status_code == 403
    listed = await client.get(f"/spaces/{fam.id}/transactions", headers=auth(h))
    assert listed.json() == []  # a transferência mora no espaço de origem


async def test_pockets_guard_uses_available_only_with_pockets(client, session):
    a = await make_user(session, "a@x.com")
    h, sp = auth(a), a.default_space_id
    src = await make_account(session, sp, name="Nubank", initial=100_000)
    dst = await make_account(session, sp, name="Itaú")
    # sem caixinhas: saldo negativo continua permitido
    assert (await _transfer(client, a, sp, src, dst, 120_000)).status_code == 201
    assert (await _acc(client, a, src))["balance_cents"] == -20_000
    # com caixinha: só o disponível sai
    src2 = await make_account(session, sp, name="Inter", initial=100_000)
    body = {"account_id": str(src2.id), "name": "Reserva", "cdi_bp": 12_000}
    pk = await client.post(f"/spaces/{sp}/pockets", headers=h, json=body)
    await client.post(
        f"/pockets/{pk.json()['id']}/deposit", headers=h, json={"amount_cents": 60_000}
    )
    r = await _transfer(client, a, sp, src2, dst, 40_001)
    assert r.status_code == 409 and r.json() == {"detail": "insufficient_available"}
    assert (await _transfer(client, a, sp, src2, dst, 40_000)).status_code == 201
    assert (await _acc(client, a, src2))["available_cents"] == 0


async def test_lgpd_export_and_delete_cover_counter_account(client, session):
    w, h = await make_user(session, "w@x.com"), await make_user(session, "h@x.com")
    fam = await make_family(session, h, w)  # h é o dono: w pode se apagar
    pessoal = await make_account(session, w.default_space_id, name="Pessoal", initial=50_000)
    conjunta = await make_account(session, fam.id, name="Conjunta")
    r = await _transfer(client, w, w.default_space_id, pessoal, conjunta, 20_000,
                        description="para a casa")  # fmt: skip
    assert r.status_code == 201
    z = zipfile.ZipFile(io.BytesIO((await client.get("/privacy/export", headers=auth(w))).content))
    tx = json.loads(z.read("data.json"))["transactions"]
    assert [(t["account_id"], t["counter_account_id"]) for t in tx] == [
        (str(pessoal.id), str(conjunta.id))
    ]
    rows = list(csv.DictReader(io.StringIO(z.read("transactions.csv").decode())))
    assert rows[0]["counter_account_id"] == str(conjunta.id)
    hz = zipfile.ZipFile(io.BytesIO((await client.get("/privacy/export", headers=auth(h))).content))
    assert "para a casa" not in hz.read("data.json").decode()  # espaço pessoal de w
    d = await client.request("DELETE", "/privacy/account", json={"password": PWD}, headers=auth(w))
    assert d.status_code == 204
    assert (await _acc(client, h, conjunta))["balance_cents"] == 0

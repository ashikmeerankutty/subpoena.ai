from __future__ import annotations

from apitest import Env


def test_create_list_revoke_cycle(env: Env) -> None:
    admin = env.auth(env.admin)
    created = env.client.post("/v1/api-keys", json={"name": "ci"}, headers=admin)
    assert created.status_code == 201
    key = created.json()
    secret = key["secret"]
    assert secret.startswith("sk_test_") and key["prefix"] == secret[:12]

    listed = env.client.get("/v1/api-keys", headers=admin).json()["data"]
    row = next(k for k in listed if k["id"] == key["id"])
    assert "secret" not in row and "hash" not in row

    assert env.client.get("/v1/evaluations", headers=env.auth(secret)).status_code == 200
    assert env.client.delete(f"/v1/api-keys/{key['id']}", headers=admin).status_code == 204
    assert env.client.get("/v1/evaluations", headers=env.auth(secret)).status_code == 401


def test_secret_is_never_stored(env: Env) -> None:
    secret = env.client.post(
        "/v1/api-keys", json={"name": "x"}, headers=env.auth(env.admin)
    ).json()["secret"]
    stored = env.client.portal.call(env.services.store.list_api_keys, env.workspace_id)  # type: ignore[union-attr]
    assert stored and all(secret not in k.model_dump_json() for k in stored)


def test_requires_admin(env: Env) -> None:
    r = env.client.post("/v1/api-keys", json={"name": "x"}, headers=env.auth(env.writer))
    assert r.status_code == 403


def test_cannot_revoke_other_workspace_key(env: Env) -> None:
    mine = env.client.post("/v1/api-keys", json={"name": "x"}, headers=env.auth(env.admin)).json()[
        "id"
    ]
    r = env.client.delete(f"/v1/api-keys/{mine}", headers=env.auth(env.other_ws_admin))
    assert r.status_code == 404

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from apitest import Env
from subpoena_api.pii import MaskPiiMiddleware
from subpoena_schemas import (
    Agent,
    Channel,
    EventType,
    MessageDirection,
    PipelineEvent,
    WitnessMessage,
    utcnow,
)

TOKENS: dict[str, dict[str, Any]] = {
    "tok-ana": {"email": "Ana@Bank.test", "email_verified": True, "name": "Ana", "nonce": "n1"},
    "tok-viv": {"email": "viv@bank.test", "email_verified": True},
    "tok-unverified": {"email": "ana@bank.test", "email_verified": False},
    "tok-stranger": {"email": "who@else.test", "email_verified": True},
}


async def fake_verifier(token: str) -> dict[str, Any]:
    # Tests send each token repeated 5x to satisfy the API's minimum token length.
    claims = TOKENS.get(token[: len(token) // 5])
    if claims is None or token != token[: len(token) // 5] * 5:
        raise ValueError("bad signature")
    return claims


@pytest.fixture
def sso(env: Env) -> Env:
    env.services.google_verifier = fake_verifier
    return env


def sign_in(env: Env, token: str, **extra: Any) -> Any:
    return env.client.post("/v1/sessions/google", json={"id_token": token * 5, **extra})


def add(env: Env, email: str, role: str, key: str | None = None) -> dict[str, Any]:
    r = env.client.post(
        "/v1/members", json={"email": email, "role": role}, headers=env.auth(key or env.admin)
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_sign_in_issues_a_role_scoped_session(sso: Env) -> None:
    add(sso, "ana@bank.test", "ANALYST")
    r = sign_in(sso, "tok-ana", nonce="n1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "ANALYST" and body["token"].startswith("ss_")
    session = sso.auth(body["token"])

    me = sso.client.get("/v1/me", headers=session).json()
    assert me["role"] == "ANALYST" and me["principal"]["email"] == "ana@bank.test"
    # Analysts can read and override but cannot manage keys or members.
    assert sso.client.get("/v1/evaluations", headers=session).status_code == 200
    assert sso.client.get("/v1/api-keys", headers=session).status_code == 403
    assert sso.client.get("/v1/members", headers=session).status_code == 403
    # Sessions never show up as API keys.
    keys = sso.client.get("/v1/api-keys", headers=sso.auth(sso.admin)).json()["data"]
    assert all(not k["prefix"].startswith("ss_") for k in keys)

    assert sso.client.delete("/v1/sessions/current", headers=session).status_code == 204
    assert sso.client.get("/v1/me", headers=session).status_code == 401


@pytest.mark.parametrize(
    ("token", "extra", "status", "problem"),
    [
        ("tok-bogus", {}, 401, "invalid-id-token"),
        ("tok-unverified", {}, 401, "unverified-email"),
        ("tok-stranger", {}, 403, "not-a-member"),
        ("tok-ana", {"nonce": "replayed"}, 401, "invalid-id-token"),
    ],
)
def test_sign_in_rejections(
    sso: Env, token: str, extra: dict[str, Any], status: int, problem: str
) -> None:
    add(sso, "ana@bank.test", "ADMIN")
    r = sign_in(sso, token, **extra)
    assert r.status_code == status and r.json()["type"].endswith(problem)


def test_sso_not_configured(env: Env) -> None:
    assert sign_in(env, "tok-ana").status_code == 404


def test_expired_session_is_rejected(sso: Env) -> None:
    add(sso, "ana@bank.test", "ADMIN")
    token = sign_in(sso, "tok-ana").json()["token"]
    store = sso.services.store
    keys = sso.client.portal.call(store.list_api_keys, sso.workspace_id)  # type: ignore[union-attr]
    session = next(k for k in keys if k.member_id)
    expired = session.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
    sso.client.portal.call(store.put_api_key, expired)  # type: ignore[union-attr]
    assert sso.client.get("/v1/me", headers=sso.auth(token)).status_code == 401


def test_role_change_and_removal_revoke_sessions_and_keep_an_admin(sso: Env) -> None:
    ana = add(sso, "ana@bank.test", "ADMIN")
    token = sign_in(sso, "tok-ana").json()["token"]
    admin = sso.auth(sso.admin)
    r = sso.client.patch(f"/v1/members/{ana['id']}", json={"role": "VIEWER"}, headers=admin)
    assert r.status_code == 200 and r.json()["role"] == "VIEWER"
    assert sso.client.get("/v1/me", headers=sso.auth(token)).status_code == 401
    assert sign_in(sso, "tok-ana").json()["role"] == "VIEWER"

    assert sso.client.delete(f"/v1/members/{ana['id']}", headers=admin).status_code == 204
    assert sign_in(sso, "tok-ana").status_code == 403
    assert (
        sso.client.post("/v1/members", json={"email": "viv@bank.test"}, headers=admin).json()[
            "role"
        ]
        == "VIEWER"
    )
    dup = sso.client.post("/v1/members", json={"email": "VIV@bank.test"}, headers=admin)
    assert dup.status_code == 409


def test_last_admin_cannot_be_removed(sso: Env) -> None:
    ana = add(sso, "ana@bank.test", "ADMIN")
    session = sso.auth(sign_in(sso, "tok-ana").json()["token"])
    # The bootstrap admin key still exists, so demoting Ana is allowed...
    keys = sso.client.get("/v1/api-keys", headers=session).json()["data"]
    for k in keys:
        sso.client.delete(f"/v1/api-keys/{k['id']}", headers=session)
    # ...but once Ana is the only admin left, she cannot be demoted or removed.
    r = sso.client.patch(f"/v1/members/{ana['id']}", json={"role": "ANALYST"}, headers=session)
    assert r.status_code == 409 and r.json()["type"].endswith("last-admin")
    assert sso.client.delete(f"/v1/members/{ana['id']}", headers=session).status_code == 409


def test_switch_workspace(sso: Env) -> None:
    add(sso, "ana@bank.test", "ADMIN")
    add(sso, "ana@bank.test", "VIEWER", key=sso.other_ws_admin)
    first = sign_in(sso, "tok-ana").json()
    assert {w["name"] for w in first["workspaces"]} == {"Acme Bank", "Other Bank"}
    other = next(w for w in first["workspaces"] if w["name"] == "Other Bank")
    switched = sso.client.post(
        "/v1/sessions/switch", json={"workspace_id": other["id"]}, headers=sso.auth(first["token"])
    ).json()
    assert switched["role"] == "VIEWER" and switched["workspace"]["id"] == other["id"]
    assert sso.client.get("/v1/me", headers=sso.auth(first["token"])).status_code == 401
    # Explicit workspace on sign-in.
    again = sign_in(sso, "tok-ana", workspace_id=sso.workspace_id).json()
    assert again["workspace"]["id"] == sso.workspace_id


def test_viewers_see_masked_pii_unless_disabled(sso: Env) -> None:
    phone, ip = "+14155550123", "203.0.113.44"
    store = sso.services.store
    msg = WitnessMessage(
        workspace_id=sso.workspace_id,
        phone=phone,
        direction=MessageDirection.INBOUND,
        channel=Channel.WHATSAPP,
        body=f"it was me, from {ip}, mail me at ana@bank.test",
    )
    event = PipelineEvent(
        evaluation_id="eval_x",
        sequence=0,
        from_agent=Agent.CLERK,
        type=EventType.TOOL_CALL,
        payload={"ip_address": ip, "phone": phone},
    )
    sso.client.portal.call(store.put_message, msg)  # type: ignore[union-attr]
    sso.client.portal.call(store.append_event, event)  # type: ignore[union-attr]
    path = f"/v1/witness/{phone}/messages"

    raw = sso.client.get(path, headers=sso.auth(sso.admin)).text
    assert phone in raw and ip in raw and "ana@bank.test" in raw

    viewer = sso.client.get(path, headers=sso.auth(sso.reader))
    assert viewer.status_code == 200
    text = viewer.text
    assert phone not in text and ip not in text and "ana@bank.test" not in text
    assert "+•••••••23" in text and "203.0.•.•" in text and "a•••@bank.test" in text
    assert viewer.json()["data"][0]["direction"] == "INBOUND"  # still valid JSON
    assert int(viewer.headers["content-length"]) == len(viewer.content)

    r = sso.client.patch("/v1/settings", json={"pii_masking": False}, headers=sso.auth(sso.admin))
    assert r.status_code == 200 and r.json()["workspace"]["settings"]["pii_masking"] is False
    assert phone in sso.client.get(path, headers=sso.auth(sso.reader)).text


def test_masking_middleware_streams_event_chunks() -> None:
    app = FastAPI()
    app.add_middleware(MaskPiiMiddleware)

    @app.get("/stream")
    async def stream(request: Request) -> StreamingResponse:
        request.state.mask_pii = True

        async def gen():  # type: ignore[no-untyped-def]
            yield 'event: pipeline\ndata: {"ip": "203.0.113.44"}\n\n'
            yield 'event: pipeline\ndata: {"phone": "+919995736582"}\n\n'

        return StreamingResponse(gen(), media_type="text/event-stream")

    body = TestClient(app).get("/stream").text
    assert "203.0.•.•" in body and "+•••••••82" in body and "113.44" not in body


def test_audit_log_records_admin_actions(sso: Env) -> None:
    admin = sso.auth(sso.admin)
    key = sso.client.post("/v1/api-keys", json={"name": "ci"}, headers=admin).json()
    sso.client.delete(f"/v1/api-keys/{key['id']}", headers=admin)
    sso.client.post(
        "/v1/policies",
        json={"thresholds": {"approve_max": 0.2, "block_min": 0.9}},
        headers=admin,
    )
    ana = add(sso, "ana@bank.test", "ANALYST")
    sso.client.patch(f"/v1/members/{ana['id']}", json={"role": "VIEWER"}, headers=admin)
    sign_in(sso, "tok-ana")
    sso.client.patch("/v1/settings", json={"name": "Acme Bank EU"}, headers=admin)

    rows = sso.client.get("/v1/audit-log", headers=admin).json()["data"]
    actions = [r["action"] for r in rows]
    assert actions == [
        "settings.updated",
        "member.signed_in",
        "member.role_changed",
        "member.added",
        "policy.published",
        "api_key.revoked",
        "api_key.created",
    ]
    policy = rows[actions.index("policy.published")]
    assert policy["after"]["thresholds"]["approve_max"] == 0.2 and policy["target"] == "v2"
    assert rows[0]["before"] == {"name": "Acme Bank"} and rows[0]["after"] == {
        "name": "Acme Bank EU"
    }
    assert rows[1]["actor"]["type"] == "MEMBER"

    filtered = sso.client.get("/v1/audit-log?action=member", headers=admin).json()["data"]
    assert {r["action"] for r in filtered} == {
        "member.signed_in",
        "member.role_changed",
        "member.added",
    }
    assert sso.client.get("/v1/audit-log", headers=sso.auth(sso.reader)).status_code == 403
    # Other workspaces see none of it.
    assert (
        sso.client.get("/v1/audit-log", headers=sso.auth(sso.other_ws_admin)).json()["data"] == []
    )


def test_invalid_policy_is_a_422_problem(env: Env) -> None:
    for path in ("/v1/policies", "/v1/policies/simulate"):
        r = env.client.post(
            path,
            json={"thresholds": {"approve_max": 0.9, "block_min": 0.2}},
            headers=env.auth(env.admin),
        )
        assert r.status_code == 422 and r.json()["type"].endswith("validation-error")

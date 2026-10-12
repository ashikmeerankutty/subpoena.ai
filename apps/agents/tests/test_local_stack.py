"""End to end over HTTP: API -> Tier 0 -> courtroom -> subpoena -> simulator reply -> verdict."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi.testclient import TestClient

from courtkit import SCENARIOS
from subpoena_agents.config import CourtSettings
from subpoena_agents.local import build_local_app
from subpoena_api.routes.twilio import twilio_signature
from subpoena_api.settings import Settings
from subpoena_api.webhooks import verify, workspace_secret

KEY = "sk_test_localstack_admin_key_0001"
H = {"Authorization": f"Bearer {KEY}"}


def client(monkeypatch, **settings: Any) -> TestClient:
    monkeypatch.setenv("SUBPOENA_LOCAL_ADMIN_KEY", KEY)
    s = Settings(
        env="test",
        sync_wait_max_ms=8000,
        sync_poll_interval_ms=20,
        twilio_auth_token="tw_test_token",
        public_base_url="https://api.example.com",
        **settings,
    )
    return TestClient(build_local_app(s, CourtSettings(llm="scripted"), bootstrap=True))


def post(c: TestClient, name: str, idem: str) -> Any:
    return c.post(
        "/v1/evaluations", json=SCENARIOS[name]["request"], headers=H | {"Idempotency-Key": idem}
    )


def wait_for(c: TestClient, eid: str, status: str, timeout: float = 5) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        ev = c.get(f"/v1/evaluations/{eid}", headers=H).json()
        if ev["status"] == status:
            return ev
        time.sleep(0.02)
    raise AssertionError(f"{eid} never reached {status}: {ev['status']}")


def test_full_subpoena_flow_over_http(monkeypatch) -> None:
    with client(monkeypatch) as c:
        r = post(c, "auto_parts_deadlock", "e2e-1")
        assert r.status_code == 202
        ev = r.json()
        assert ev["status"] == "AWAITING_TESTIMONY" and ev["subpoena"]["channel"] == "WHATSAPP"
        sub = c.get(f"/v1/subpoenas/{ev['subpoena']['id']}", headers=H).json()
        code = next(
            m["body"].split("code is ")[1][:6] for m in sub["messages"] if "code is" in m["body"]
        )

        r = c.post(
            "/v1/simulator/witness-reply",
            headers=H,
            json={"phone": "+14155550123", "body": f"Yes, parts for my BMW E36 project {code}"},
        )
        assert r.json() == {
            "matched": True,
            "subpoena_id": sub["id"],
            "code_received": True,
            "text_received": True,
        }
        done = wait_for(c, ev["evaluation_id"], "RULED")
        assert done["verdict"] == "APPROVE" and done["testimony"]["claims"]["confirms_transaction"]

        # SSE replays the whole transcript and ends.
        with c.stream(
            "GET",
            f"/v1/evaluations/{ev['evaluation_id']}/events",
            headers=H | {"Accept": "text/event-stream"},
        ) as s:
            text = "".join(s.iter_text())
        types = [
            json.loads(line[6:])["type"]
            for line in text.splitlines()
            if line.startswith('data: {"event_id"')
        ]
        assert types[0] == "CASE_OPENED" and types[-1] == "VERDICT" and "event: end" in text

        # Analyst override -> APPEALED, OVERRIDE event.
        r = c.post(
            f"/v1/evaluations/{ev['evaluation_id']}/override",
            headers=H,
            json={"verdict": "BLOCK", "reason": "Chargeback received later"},
        )
        assert (
            r.json()["status"] == "APPEALED"
            and r.json()["override"]["previous_verdict"] == "APPROVE"
        )

        stats = c.get("/v1/stats/overview", headers=H).json()
        assert stats["evaluations"] == 1 and stats["subpoenas"] == 1
        assert stats["subpoena_resolution_rate"] == 1.0


def test_sync_response_when_courtroom_rules_fast(monkeypatch) -> None:
    with client(monkeypatch) as c:
        r = post(c, "clear_fraud", "e2e-2")
        assert r.status_code == 200 and r.json()["verdict"] == "BLOCK"


def test_twilio_inbound_requires_valid_signature(monkeypatch) -> None:
    with client(monkeypatch) as c:
        ev = post(c, "auto_parts_deadlock", "e2e-3").json()
        form = {"From": "whatsapp:+14155550123", "Body": "No, not me", "MessageSid": "SM1"}
        bad = c.post(
            "/v1/webhooks/twilio/inbound", data=form, headers={"X-Twilio-Signature": "nope"}
        )
        assert bad.status_code == 403
        sig = twilio_signature(
            "tw_test_token", "https://api.example.com/v1/webhooks/twilio/inbound", form
        )
        ok = c.post("/v1/webhooks/twilio/inbound", data=form, headers={"X-Twilio-Signature": sig})
        assert ok.status_code == 200 and "<Response>" in ok.text
        sub = c.get(f"/v1/subpoenas/{ev['subpoena']['id']}", headers=H).json()
        assert sub["reply_text"] == "No, not me"
        assert sub["messages"][-2]["direction"] == "INBOUND"


def test_outbound_webhook_signature_roundtrip() -> None:
    secret = workspace_secret("master", "ws_1")
    from subpoena_api.webhooks import sign

    body = b'{"type":"evaluation.completed"}'
    assert verify(secret, body, sign(secret, body))
    assert not verify(secret, body + b" ", sign(secret, body))

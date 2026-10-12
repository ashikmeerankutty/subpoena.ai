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
            "photos_received": 0,
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


def test_overview_reports_customer_impact(monkeypatch) -> None:
    with client(monkeypatch) as c:
        assert post(c, "coffee", "imp-1").json()["verdict"] == "APPROVE"
        assert post(c, "clear_fraud", "imp-2").json()["verdict"] == "BLOCK"
        sim = post(c, "sim_swap", "imp-3").json()
        wait_for(c, sim["evaluation_id"], "ESCALATED")
        ev = post(c, "auto_parts_deadlock", "imp-4").json()
        sub = c.get(f"/v1/subpoenas/{ev['subpoena']['id']}", headers=H).json()
        code = next(
            m["body"].split("code is ")[1][:6] for m in sub["messages"] if "code is" in m["body"]
        )
        c.post(
            "/v1/simulator/witness-reply",
            headers=H,
            json={"phone": "+14155550123", "body": f"Yes, it was me {code}"},
        )
        wait_for(c, ev["evaluation_id"], "RULED")

        impact = c.get("/v1/stats/overview", headers=H).json()["impact"]
        assert impact["legit_spend_saved"] == {"count": 1, "amounts": {"USD": "4500.00"}}
        assert impact["fraud_stopped"]["count"] == 2
        assert impact["fraud_stopped"]["amounts"] == {"USD": "14300.00"}
        assert impact["customers_not_contacted_rate"] == 0.5
        assert impact["witness_protection"]["sim_swap_blocked"] == 1
        assert impact["median_resolution_s"] is not None


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


def test_receipt_photo_over_http(monkeypatch) -> None:
    import base64

    with client(monkeypatch) as c:
        ev = post(c, "auto_parts_deadlock", "e2e-photo").json()
        sub = c.get(f"/v1/subpoenas/{ev['subpoena']['id']}", headers=H).json()
        code = next(
            m["body"].split("code is ")[1][:6] for m in sub["messages"] if "code is" in m["body"]
        )
        assert "photo of the receipt" in sub["messages"][0]["body"]
        # A WhatsApp photo with a caption: text, code and receipt arrive together.
        photo = json.dumps({"merchant": "AutoZone", "amount": "4500.00"}).encode()
        r = c.post(
            "/v1/simulator/witness-reply",
            headers=H,
            json={
                "phone": "+14155550123",
                "body": f"Yes, parts for my BMW E36 project {code}",
                "photos": [
                    {"content_type": "image/png", "data_base64": base64.b64encode(photo).decode()}
                ],
            },
        )
        assert r.json()["photos_received"] == 1
        done = wait_for(c, ev["evaluation_id"], "RULED")
        assert done["verdict"] == "APPROVE"
        assert done["testimony"]["receipt"]["result"] == "MATCH"

        media_id = done["testimony"]["receipt"]["media_id"]
        img = c.get(f"/v1/media/{media_id}", headers=H)
        assert img.status_code == 200 and img.content == photo
        assert img.headers["content-type"] == "image/png"
        msgs = c.get(f"/v1/subpoenas/{sub['id']}", headers=H).json()["messages"]
        assert any(m["media"] and m["media"][0]["id"] == media_id for m in msgs)
        assert c.get("/v1/media/med_doesnotexist", headers=H).status_code == 404

        bad = c.post(
            "/v1/simulator/witness-reply",
            headers=H,
            json={
                "phone": "+14155550123",
                "photos": [{"content_type": "image/png", "data_base64": "@@@"}],
            },
        )
        assert bad.status_code == 422
        empty = c.post("/v1/simulator/witness-reply", headers=H, json={"phone": "+14155550123"})
        assert empty.status_code == 422


def test_twilio_photo_is_downloaded_from_twilio_only(monkeypatch) -> None:
    import httpx

    fetched: list[str] = []
    real_get = httpx.AsyncClient.get

    async def fake_get(self, url, *a, **kw):  # type: ignore[no-untyped-def]
        if str(url).startswith("https://api.twilio.com/"):
            fetched.append(str(url))
            return httpx.Response(200, content=b'{"merchant": "AutoZone", "amount": "4500"}')
        return await real_get(self, url, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with client(monkeypatch, twilio_account_sid="ACtest") as c:
        ev = post(c, "auto_parts_deadlock", "e2e-twilio-photo").json()
        params = {
            "From": "whatsapp:+14155550123",
            "Body": "Yes, my BMW project",
            "MessageSid": "SMx",
            "NumMedia": "2",
            "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages/MMx/Media/ME1",
            "MediaContentType0": "image/jpeg",
            "MediaUrl1": "https://evil.example/steal",
            "MediaContentType1": "image/jpeg",
        }
        url = "https://api.example.com/v1/webhooks/twilio/inbound"
        sig = twilio_signature("tw_test_token", url, params)
        r = c.post("/v1/webhooks/twilio/inbound", data=params, headers={"X-Twilio-Signature": sig})
        assert r.status_code == 200
        assert fetched == [params["MediaUrl0"]]
        sub = c.get(f"/v1/subpoenas/{ev['subpoena']['id']}", headers=H).json()
        assert len(sub["media"]) == 1 and sub["media"][0]["source"] == "twilio"

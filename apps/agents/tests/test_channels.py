"""Subpoena calls and channel fallback, end to end over HTTP with signed Twilio webhooks."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient
from test_local_stack import H, client, wait_for

from courtkit import SCENARIOS
from subpoena_api.routes.twilio import twilio_signature

PHONE = "+14155550123"
BASE = "https://api.example.com"


def twilio(c: TestClient, path: str, params: dict[str, str]) -> Any:
    sig = twilio_signature("tw_test_token", BASE + path, params)
    return c.post(path, data=params, headers={"X-Twilio-Signature": sig})


def channels(c: TestClient, *names: str) -> None:
    r = c.post(
        "/v1/policies",
        json={"subpoena": {"min_amount": "50.00", "channels": list(names), "timeout_seconds": 900}},
        headers=H,
    )
    assert r.status_code == 201, r.text


def subpoena(c: TestClient, ev: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = c.get(f"/v1/subpoenas/{ev['subpoena']['id']}", headers=H).json()
    return result


def until(c: TestClient, ev: dict[str, Any], channel: str) -> dict[str, Any]:
    for _ in range(250):
        if (sub := subpoena(c, ev))["channel"] == channel:
            return sub
        time.sleep(0.02)
    raise AssertionError(f"subpoena never moved to {channel}: {sub['channels_tried']}")


def code_of(sub: dict[str, Any]) -> str:
    return next(
        m["body"].split("code is ")[1][:6] for m in sub["messages"] if "code is" in m["body"]
    )


def evaluate(c: TestClient, idem: str, allowed: list[str]) -> dict[str, Any]:
    req = SCENARIOS["auto_parts_deadlock"]["request"]
    req = {**req, "witness": {**req["witness"], "allowed_channels": allowed}}
    r = c.post("/v1/evaluations", json=req, headers=H | {"Idempotency-Key": idem})
    assert r.status_code == 202, r.text
    ev: dict[str, Any] = r.json()
    return ev


def test_voice_subpoena_collects_code_and_spoken_answer(monkeypatch) -> None:
    with client(monkeypatch) as c:
        channels(c, "VOICE", "SMS")
        ev = evaluate(c, "voice-1", ["WHATSAPP", "SMS", "VOICE"])
        assert ev["subpoena"]["channel"] == "VOICE"
        sub = subpoena(c, ev)
        call = next(m for m in sub["messages"] if m["channel"] == "VOICE")
        assert "calling about a $4,500.00 payment to AutoZone Online" in call["body"]

        call_params = {"CallSid": sub["twilio_sid"], "To": PHONE, "Direction": "outbound-api"}
        start = twilio(c, "/v1/webhooks/twilio/voice/start", call_params)
        assert start.status_code == 200 and "calling about" in start.text
        assert 'action="https://api.example.com/v1/webhooks/twilio/voice/code"' in start.text

        code = twilio(c, "/v1/webhooks/twilio/voice/code", call_params | {"Digits": code_of(sub)})
        assert 'input="speech"' in code.text and "/voice/answer" in code.text

        answer = twilio(
            c,
            "/v1/webhooks/twilio/voice/answer",
            call_params | {"SpeechResult": "Yes, those are parts for my BMW project"},
        )
        assert "<Hangup/>" in answer.text

        done = wait_for(c, ev["evaluation_id"], "RULED")
        assert done["verdict"] == "APPROVE"
        msgs = subpoena(c, ev)["messages"]
        inbound = [m["body"] for m in msgs if m["direction"] == "INBOUND"]
        assert inbound[-1] == "Yes, those are parts for my BMW project"
        # The outcome can't be said on a call that has ended, so it goes by text.
        assert msgs[-1]["direction"] == "OUTBOUND" and msgs[-1]["channel"] == "SMS"
        assert not any("you're verified" in m["body"] for m in msgs)


def test_witness_calling_back_hears_the_open_question(monkeypatch) -> None:
    with client(monkeypatch) as c:
        channels(c, "VOICE")
        evaluate(c, "voice-2", ["VOICE"])
        params = {"CallSid": "CAin", "From": PHONE, "Direction": "inbound"}
        r = twilio(c, "/v1/webhooks/twilio/voice/inbound", params)
        assert "/voice/code" in r.text
        unknown = twilio(c, "/v1/webhooks/twilio/voice/inbound", params | {"From": "+15550000000"})
        assert "no open request" in unknown.text and "<Gather" not in unknown.text


def test_voice_webhooks_require_a_twilio_signature(monkeypatch) -> None:
    with client(monkeypatch) as c:
        for step in ("start", "inbound", "code", "answer", "status"):
            r = c.post(
                f"/v1/webhooks/twilio/voice/{step}",
                data={"To": PHONE, "Digits": "123456"},
                headers={"X-Twilio-Signature": "nope"},
            )
            assert r.status_code == 403


def test_undelivered_subpoena_moves_to_the_next_channel(monkeypatch) -> None:
    with client(monkeypatch) as c:
        ev = evaluate(c, "fallback-1", ["WHATSAPP", "SMS"])
        sub = subpoena(c, ev)
        assert sub["channel"] == "WHATSAPP" and sub["channels_tried"] == ["WHATSAPP"]

        # e.g. the WhatsApp 24-hour window has closed (Twilio error 63016)
        status = {"MessageSid": sub["twilio_sid"], "MessageStatus": "undelivered"}
        r = twilio(c, "/v1/webhooks/twilio/status", status | {"To": f"whatsapp:{PHONE}"})
        assert r.status_code == 204
        sub = until(c, ev, "SMS")
        assert sub["channels_tried"] == ["WHATSAPP", "SMS"] and sub["delivery_status"] == "QUEUED"
        assert "Reply YES or NO" in sub["messages"][-1]["body"]
        assert sub["messages"][-1]["channel"] == "SMS"

        # The SMS fails too: nothing left, so the case waits for its deadline.
        twilio(
            c,
            "/v1/webhooks/twilio/status",
            {"MessageSid": sub["twilio_sid"], "MessageStatus": "failed", "To": PHONE},
        )
        events = c.get(f"/v1/evaluations/{ev['evaluation_id']}", headers=H).json()
        assert events["status"] == "AWAITING_TESTIMONY"

        # A reply on the new channel still completes the case; the simulator replies on the
        # subpoena's current channel unless told otherwise.
        c.post(
            "/v1/simulator/witness-reply",
            headers=H,
            json={"phone": PHONE, "body": f"Yes, my BMW parts {code_of(sub)}"},
        )
        inbound = [m for m in subpoena(c, ev)["messages"] if m["direction"] == "INBOUND"]
        assert inbound[-1]["channel"] == "SMS"
        assert wait_for(c, ev["evaluation_id"], "RULED")["verdict"] == "APPROVE"


def test_unanswered_call_falls_back_and_late_status_is_ignored(monkeypatch) -> None:
    with client(monkeypatch) as c:
        channels(c, "VOICE", "WHATSAPP")
        ev = evaluate(c, "fallback-2", ["VOICE", "WHATSAPP"])
        sub = subpoena(c, ev)
        call = {"CallSid": sub["twilio_sid"], "To": PHONE, "Direction": "outbound-api"}
        twilio(c, "/v1/webhooks/twilio/voice/status", call | {"CallStatus": "no-answer"})
        sub = until(c, ev, "WHATSAPP")
        assert sub["channels_tried"] == ["VOICE", "WHATSAPP"]
        # A stale status for the old call must not trigger another resend.
        twilio(c, "/v1/webhooks/twilio/voice/status", call | {"CallStatus": "failed"})
        assert subpoena(c, ev)["channels_tried"] == ["VOICE", "WHATSAPP"]


def test_partial_keypad_code_is_asked_again_and_never_becomes_testimony(monkeypatch) -> None:
    with client(monkeypatch) as c:
        channels(c, "VOICE")
        ev = evaluate(c, "voice-3", ["VOICE"])
        sub = subpoena(c, ev)
        call = {"CallSid": sub["twilio_sid"], "To": PHONE, "Direction": "outbound-api"}
        first = twilio(c, "/v1/webhooks/twilio/voice/code", call | {"Digits": "53"})
        assert "/voice/code-retry" in first.text and 'input="dtmf"' in first.text
        last = twilio(c, "/v1/webhooks/twilio/voice/code-retry", call | {"Digits": ""})
        assert "<Gather" not in last.text and "reply to our text" in last.text
        sub = subpoena(c, ev)
        assert sub["reply_text"] is None and sub["code_attempts"] == 0
        assert not [m for m in sub["messages"] if m["direction"] == "INBOUND"]

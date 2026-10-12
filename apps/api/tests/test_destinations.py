from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from apitest import SCENARIOS, Env
from subpoena_api.destinations import Deliverer, bigquery_row, slack_message
from subpoena_api.webhooks import verify
from subpoena_schemas import Evaluation, EvaluationRequest

SLACK = "https://hooks.slack.com/services/T000/B000/XXXX"


class Recorder:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


@pytest.fixture
def dest_env(env: Env) -> tuple[Env, Recorder]:
    rec = Recorder()
    n = env.services.notifier
    n.store = env.services.store
    n.backoff = (0, 0, 0)
    n._http = httpx.AsyncClient(transport=httpx.MockTransport(rec))
    return env, rec


def create(env: Env, **body: Any) -> Any:
    return env.client.post("/v1/destinations", json=body, headers=env.auth(env.admin))


@pytest.mark.parametrize(
    ("dtype", "config", "message"),
    [
        ("WEBHOOK", {"url": "http://bank.example/hook"}, "https"),
        ("WEBHOOK", {"url": "https://169.254.169.254/latest"}, "private"),
        ("WEBHOOK", {"url": "https://10.1.2.3/hook"}, "private"),
        ("WEBHOOK", {"url": "https://metadata.google.internal/x"}, "not allowed"),
        ("SLACK", {"url": "https://evil.example/services/x"}, "Slack"),
        ("PUBSUB", {"topic": "decisions"}, "projects/"),
        ("BIGQUERY", {"table": "dataset_only"}, "<project>"),
    ],
)
def test_unsafe_or_malformed_destinations_are_rejected(
    env: Env, dtype: str, config: dict[str, str], message: str
) -> None:
    r = create(env, name="x", type=dtype, config=config)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_unknown_event_types_are_rejected(env: Env) -> None:
    r = create(env, name="x", type="SLACK", config={"url": SLACK}, enabled_events=["nope"])
    assert r.status_code == 422


def test_webhook_test_delivery_is_signed(dest_env: tuple[Env, Recorder]) -> None:
    env, rec = dest_env
    d = create(
        env, name="Fraud ops", type="WEBHOOK", config={"url": "https://hooks.bank.example/subpoena"}
    ).json()
    assert d["signing_secret"].startswith("whsec_")
    r = env.client.post(f"/v1/destinations/{d['id']}/test", headers=env.auth(env.admin)).json()
    assert r["status"] == "SUCCESS" and r["response_code"] == 200 and r["attempts"] == 1
    req = rec.requests[0]
    assert str(req.url) == "https://hooks.bank.example/subpoena"
    assert verify(d["signing_secret"], req.content, req.headers["Subpoena-Signature"])
    assert json.loads(req.content)["type"] == "destination.test"


def test_fan_out_respects_event_filters_and_logs_failures(dest_env: tuple[Env, Recorder]) -> None:
    env, rec = dest_env
    slack = create(
        env,
        name="#fraud-alerts",
        type="SLACK",
        config={"url": SLACK},
        enabled_events=["evaluation.escalated"],
    ).json()
    hook = create(
        env, name="All events", type="WEBHOOK", config={"url": "https://hooks.bank.example/a"}
    ).json()
    req = EvaluationRequest.model_validate(SCENARIOS["auto_parts_deadlock"]["request"])
    ev = Evaluation(
        workspace_id=env.workspace_id,
        transaction=req.transaction(),
        witness=req.witness,
        options=req.options,
        policy_version=1,
    )
    notify = env.services.notifier.notify
    env.client.portal.call(notify, ev, "evaluation.completed", {"verdict": "APPROVE"})  # type: ignore[union-attr]
    assert [str(r.url) for r in rec.requests] == ["https://hooks.bank.example/a"]

    rec.status = 503  # retried, then recorded as failed
    env.client.portal.call(notify, ev, "evaluation.escalated", {"reason": "no reply"})  # type: ignore[union-attr]
    log = env.client.get("/v1/deliveries", headers=env.auth(env.admin)).json()["data"]
    latest = {row["destination_id"]: row for row in reversed(log)}
    assert latest[slack["id"]]["status"] == "FAILED" and latest[slack["id"]]["attempts"] == 3
    assert latest[slack["id"]]["response_code"] == 503
    slack_body = json.loads(next(r for r in reversed(rec.requests) if str(r.url) == SLACK).content)
    assert "evaluation.escalated" in slack_body["text"] and "4,500.00" in slack_body["text"]

    rec.status = 400  # client errors are not retried
    env.client.post(f"/v1/destinations/{hook['id']}/test", headers=env.auth(env.admin))
    only = env.client.get(
        f"/v1/deliveries?destination_id={hook['id']}", headers=env.auth(env.admin)
    ).json()["data"]
    assert only[0]["attempts"] == 1 and only[0]["status"] == "FAILED"

    listed = {
        d["id"]: d
        for d in env.client.get("/v1/destinations", headers=env.auth(env.admin)).json()["data"]
    }
    assert listed[slack["id"]]["failure_rate"] == 1.0 and listed[hook["id"]]["deliveries"] == 3
    assert "signing_secret" not in listed[hook["id"]]


def test_disable_update_delete_and_audit(dest_env: tuple[Env, Recorder]) -> None:
    env, _ = dest_env
    admin = env.auth(env.admin)
    d = create(env, name="x", type="WEBHOOK", config={"url": "https://hooks.bank.example/a"}).json()
    r = env.client.patch(
        f"/v1/destinations/{d['id']}", json={"enabled": False, "name": "y"}, headers=admin
    )
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert env.client.delete(f"/v1/destinations/{d['id']}", headers=admin).status_code == 204
    assert env.client.get(f"/v1/destinations/{d['id']}", headers=admin).status_code == 404
    actions = [
        a["action"]
        for a in env.client.get("/v1/audit-log?action=destination", headers=admin).json()["data"]
    ]
    assert actions == ["destination.deleted", "destination.updated", "destination.created"]
    assert env.client.get("/v1/destinations", headers=env.auth(env.reader)).status_code == 403


def test_pubsub_and_bigquery_adapters(
    dest_env: tuple[Env, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    env, _ = dest_env
    sent: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(
        Deliverer, "_publish", lambda self, topic, e: sent.append(("pubsub", topic, e))
    )
    monkeypatch.setattr(
        Deliverer, "_insert", lambda self, table, e: sent.append(("bq", table, bigquery_row(e)))
    )
    p = create(
        env, name="ps", type="PUBSUB", config={"topic": "projects/acme-bank/topics/decisions"}
    ).json()
    b = create(
        env, name="bq", type="BIGQUERY", config={"table": "acme-bank.fraud.decisions"}
    ).json()
    for d in (p, b):
        assert (
            env.client.post(f"/v1/destinations/{d['id']}/test", headers=env.auth(env.admin)).json()[
                "status"
            ]
            == "SUCCESS"
        )
    assert sent[0][:2] == ("pubsub", "projects/acme-bank/topics/decisions")
    kind, table, row = sent[1]
    assert (kind, table) == ("bq", "acme-bank.fraud.decisions")
    assert (
        row["event_type"] == "destination.test"
        and row["verdict"] == "APPROVE"
        and json.loads(row["data"])
    )


def test_slack_message_links_to_the_console() -> None:
    event = {
        "type": "evaluation.completed",
        "data": {"evaluation_id": "eval_1", "reason": "Witness confirmed"},
        "evaluation": {
            "verdict": "BLOCK",
            "status": "RULED",
            "p_fraud": 0.97,
            "amount": "4500.00",
            "currency": "USD",
            "merchant": "AutoZone Online",
        },
    }
    msg = slack_message(event, "https://console.example")
    assert msg["text"].startswith("⛔") and "<https://console.example/cases/eval_1|" in json.dumps(
        msg
    )

from __future__ import annotations

import pytest

from apitest import SCENARIOS, Env, scenario


def post(env: Env, body: dict, key: str | None = None, idem: str | None = "k1"):
    headers = env.auth(key or env.writer)
    if idem is not None:
        headers["Idempotency-Key"] = idem
    return env.client.post("/v1/evaluations", json=body, headers=headers)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenarios_route_as_expected(env: Env, name: str) -> None:
    expected = SCENARIOS[name]["expected"]
    r = post(env, scenario(name), idem=name)
    body = r.json()
    assert body["tier0"]["route"] == expected["tier0_route"], body["tier0"]
    if expected["tier0_route"] == "COURT":
        assert r.status_code == 202
        assert body["status"] == "RECEIVED" and body["verdict"] is None
        assert env.publisher.messages == [
            (
                "evaluations.created",
                {"evaluation_id": body["evaluation_id"], "workspace_id": env.workspace_id},
            )
        ]
    else:
        assert r.status_code == 200
        assert body["status"] == "RULED" and body["verdict"] == expected["verdict"]
        assert env.publisher.messages == []


def test_coffee_then_get_and_events(env: Env) -> None:
    created = post(env, scenario("coffee")).json()
    eid = created["evaluation_id"]
    got = env.client.get(f"/v1/evaluations/{eid}", headers=env.auth(env.reader))
    assert got.status_code == 200 and got.json() == created
    assert created["links"] == {
        "self": f"/v1/evaluations/{eid}",
        "events": f"/v1/evaluations/{eid}/events",
    }
    events = env.client.get(f"/v1/evaluations/{eid}/events", headers=env.auth(env.reader)).json()
    assert [(e["sequence"], e["type"]) for e in events["data"]] == [
        (0, "CASE_OPENED"),
        (1, "VERDICT"),
    ]


def test_sanctioned_country_reports_rule(env: Env) -> None:
    body = post(env, scenario("sanctioned_country")).json()
    assert body["tier0"]["rules_hit"] == ["SANCTIONED_COUNTRY:KP"]
    assert "SANCTIONED_COUNTRY" in body["rationale"]


def test_unknown_user_goes_to_court(env: Env) -> None:
    r = post(env, scenario("auto_parts_deadlock", user_id="usr_nobody", amount=900))
    assert r.status_code == 202
    assert r.json()["tier0"]["signals"]["no_baseline"] == 1.0


class TestIdempotency:
    def test_required(self, env: Env) -> None:
        r = post(env, scenario("coffee"), idem=None)
        assert r.status_code == 400
        assert r.headers["content-type"] == "application/problem+json"
        assert r.json()["type"].endswith("/idempotency-key-required")

    def test_replay_returns_original(self, env: Env) -> None:
        first = post(env, scenario("auto_parts_deadlock"))
        again = post(env, scenario("auto_parts_deadlock"))
        assert again.status_code == first.status_code == 202
        assert again.json() == first.json()
        assert again.headers["idempotent-replayed"] == "true"
        assert len(env.publisher.messages) == 1

    def test_reuse_with_different_body(self, env: Env) -> None:
        post(env, scenario("coffee"))
        r = post(env, scenario("coffee", amount=13.00))
        assert r.status_code == 422
        assert r.json()["type"].endswith("/idempotency-key-reused")

    def test_scoped_per_workspace(self, env: Env) -> None:
        a = post(env, scenario("coffee"))
        b = post(env, scenario("coffee"), key=env.other_ws_admin)
        assert a.json()["evaluation_id"] != b.json()["evaluation_id"]


class TestAuth:
    def test_missing_key(self, env: Env) -> None:
        r = env.client.get("/v1/evaluations")
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"
        assert r.json()["status"] == 401

    def test_bad_key(self, env: Env) -> None:
        r = env.client.get("/v1/evaluations", headers=env.auth("sk_test_nope"))
        assert r.status_code == 401

    def test_read_only_cannot_write(self, env: Env) -> None:
        r = post(env, scenario("coffee"), key=env.reader)
        assert r.status_code == 403
        assert r.json()["type"].endswith("/insufficient-scope")

    def test_tenant_isolation(self, env: Env) -> None:
        eid = post(env, scenario("coffee")).json()["evaluation_id"]
        h = env.auth(env.other_ws_admin)
        assert env.client.get(f"/v1/evaluations/{eid}", headers=h).status_code == 404
        assert env.client.get(f"/v1/evaluations/{eid}/events", headers=h).status_code == 404
        assert env.client.get("/v1/evaluations", headers=h).json()["data"] == []


def test_validation_error_is_problem_json(env: Env) -> None:
    r = post(env, scenario("coffee", currency="usd", amount=-5))
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"].endswith("/validation-error")
    assert {tuple(e["loc"][-1:]) for e in body["errors"]} == {("currency",), ("amount",)}


def test_not_found_is_problem_json(env: Env) -> None:
    r = env.client.get("/v1/evaluations/eval_missing", headers=env.auth(env.reader))
    assert r.status_code == 404 and r.json()["instance"] == "/v1/evaluations/eval_missing"


class TestList:
    def _seed(self, env: Env, n: int) -> list[str]:
        ids = []
        for i in range(n):
            name = "coffee" if i % 2 else "auto_parts_deadlock"
            r = post(env, scenario(name, transaction_id=f"tx_{i}"), idem=f"i{i}")
            ids.append(r.json()["evaluation_id"])
        return ids

    def test_pagination_walks_all_newest_first(self, env: Env) -> None:
        ids = self._seed(env, 7)
        seen, token = [], None
        while True:
            params = {"limit": 3} | ({"page_token": token} if token else {})
            page = env.client.get(
                "/v1/evaluations", params=params, headers=env.auth(env.reader)
            ).json()
            seen += [e["evaluation_id"] for e in page["data"]]
            token = page["meta"]["next_page_token"]
            if not token:
                break
        assert sorted(seen) == sorted(ids) and len(seen) == 7
        created = [
            env.client.get(f"/v1/evaluations/{i}", headers=env.auth(env.reader)).json()[
                "created_at"
            ]
            for i in seen
        ]
        assert created == sorted(created, reverse=True)

    def test_filters(self, env: Env) -> None:
        self._seed(env, 4)
        h = env.auth(env.reader)
        ruled = env.client.get("/v1/evaluations?verdict=APPROVE", headers=h).json()["data"]
        assert len(ruled) == 2 and all(e["verdict"] == "APPROVE" for e in ruled)
        pending = env.client.get("/v1/evaluations?status=RECEIVED", headers=h).json()["data"]
        assert len(pending) == 2
        assert env.client.get("/v1/evaluations?user_id=usr_x", headers=h).json()["data"] == []

    def test_bad_page_token(self, env: Env) -> None:
        r = env.client.get("/v1/evaluations?page_token=%%%", headers=env.auth(env.reader))
        assert r.status_code == 400 and r.json()["type"].endswith("/invalid-page-token")

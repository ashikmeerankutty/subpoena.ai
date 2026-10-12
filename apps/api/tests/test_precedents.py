from __future__ import annotations

from apitest import SCENARIOS, Env
from subpoena_schemas import (
    Evaluation,
    EvaluationRequest,
    EvaluationStatus,
    EvidenceFinding,
    Severity,
    Verdict,
)
from subpoena_store import precedent_for


def ruled_case(env: Env, scenario: str, verdict: Verdict, tx: str) -> Evaluation:
    req = EvaluationRequest.model_validate(SCENARIOS[scenario]["request"] | {"transaction_id": tx})
    ev = Evaluation(
        workspace_id=env.workspace_id,
        transaction=req.transaction(),
        witness=req.witness,
        options=req.options,
        policy_version=1,
        status=EvaluationStatus.RULED,
        verdict=verdict,
        findings=[
            EvidenceFinding(
                id="F1",
                agent="device",
                type="NEW_DEVICE",
                severity=Severity.MEDIUM,
                supports="FRAUD",
                detail="New device",
                source_ref="mcp:device",
            ),
            EvidenceFinding(
                id="F2",
                agent="velocity",
                type="AMOUNT_SPIKE",
                severity=Severity.HIGH,
                supports="FRAUD",
                detail="36x average",
                source_ref="mcp:velocity",
            ),
        ],
    )
    call = env.client.portal.call  # type: ignore[union-attr]
    call(env.services.store.put_evaluation, ev)
    p = precedent_for(ev)
    assert p is not None
    call(env.services.store.put_precedent, p)
    return ev


def test_search_similar_and_override(env: Env) -> None:
    h = env.auth(env.reader)
    approved = ruled_case(env, "auto_parts_deadlock", Verdict.APPROVE, "tx_a")
    other = ruled_case(env, "auto_parts_deadlock", Verdict.APPROVE, "tx_b")

    listed = env.client.get("/v1/precedents", headers=h).json()
    assert listed["meta"]["total"] == 6  # 2 workspace rulings + 4 seed
    assert all("embedding" not in p for p in listed["data"])

    hits = env.client.get(
        "/v1/precedents", params={"q": "auto parts new device AutoZone"}, headers=h
    ).json()["data"]
    sims = [p["similarity"] for p in hits]
    assert sims == sorted(sims, reverse=True) and {"CASE", "SEED"} <= {p["source"] for p in hits}

    similar = env.client.get(f"/v1/evaluations/{approved.evaluation_id}/similar", headers=h).json()[
        "data"
    ]
    assert similar[0]["evaluation_id"] == other.evaluation_id  # never itself
    assert approved.evaluation_id not in {p.get("evaluation_id") for p in similar}

    # An analyst's correction replaces the precedent's label.
    r = env.client.post(
        f"/v1/evaluations/{approved.evaluation_id}/override",
        json={"verdict": "BLOCK", "reason": "Chargeback filed"},
        headers=env.auth(env.admin),
    )
    assert r.status_code == 200
    mine = {
        p["evaluation_id"]: p
        for p in env.client.get("/v1/precedents", headers=h).json()["data"]
        if p["evaluation_id"]
    }
    assert (
        mine[approved.evaluation_id]["label"] == "FRAUD"
        and mine[approved.evaluation_id]["source"] == "OVERRIDE"
    )

    # HOLD removes it; admins can delete; seed precedents cannot be deleted.
    env.client.post(
        f"/v1/evaluations/{other.evaluation_id}/override",
        json={"verdict": "HOLD", "reason": "unsure"},
        headers=env.auth(env.admin),
    )
    ids = {p["id"] for p in env.client.get("/v1/precedents", headers=h).json()["data"]}
    assert f"prec_{other.evaluation_id.removeprefix('eval_')}" not in ids
    pid = mine[approved.evaluation_id]["id"]
    assert env.client.delete(f"/v1/precedents/{pid}", headers=h).status_code == 403
    assert (
        env.client.delete(f"/v1/precedents/{pid}", headers=env.auth(env.admin)).status_code == 204
    )
    assert (
        env.client.delete("/v1/precedents/seed_P1", headers=env.auth(env.admin)).status_code == 404
    )

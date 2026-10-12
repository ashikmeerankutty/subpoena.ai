from __future__ import annotations

import json
import time
from decimal import Decimal

from apitest import SCENARIOS, SETTINGS
from subpoena_api.baselines import SeedBaselines
from subpoena_api.tier0 import prescreen, score
from subpoena_schemas import EvaluationRequest, Policy, Tier0Route

POLICY = Policy(workspace_id="ws")
BASELINES = SeedBaselines(SETTINGS.seed_dir)


def txn(name: str, **kw: object):
    return EvaluationRequest.model_validate(SCENARIOS[name]["request"] | kw).transaction()


def test_score_is_monotonic_in_signals() -> None:
    assert score({}) == 0.0
    assert score({"new_device": 1.0}) < score({"new_device": 1.0, "new_ip": 1.0})
    assert 0 <= score({k: 1.0 for k in ("amount_spike", "new_device", "mcc_risk")}) <= 1


def test_amount_ceiling_hard_rule() -> None:
    t = txn("coffee", amount=60000)
    result = prescreen(t, BASELINES.get(t.user_id), POLICY)
    assert result.route is Tier0Route.EXIT_BLOCK and result.rules_hit == ["AMOUNT_CEILING"]


def test_known_bad_device_hard_rule() -> None:
    policy = Policy.model_validate(
        {"workspace_id": "ws", "hard_rules": {"known_bad_devices": ["abc-123"]}}
    )
    t = txn("auto_parts_deadlock")
    assert prescreen(t, BASELINES.get(t.user_id), policy).rules_hit == ["KNOWN_BAD_DEVICE"]


def test_amount_within_p95_is_not_a_spike() -> None:
    b = BASELINES.get("usr_9921")
    assert b is not None
    t = txn("auto_parts_deadlock", amount=float(b.p95_amount - Decimal(1)))
    assert "amount_spike" not in prescreen(t, b, POLICY).signals


def test_p95_latency_under_100ms() -> None:
    scenarios = [txn(n) for n in SCENARIOS]
    timings = []
    for _ in range(200):
        for t in scenarios:
            start = time.perf_counter()
            prescreen(t, BASELINES.get(t.user_id), POLICY)
            timings.append(time.perf_counter() - start)
    timings.sort()
    assert timings[int(len(timings) * 0.95)] < 0.1


def test_seed_scenarios_file_is_valid() -> None:
    for s in json.loads((SETTINGS.seed_dir / "scenarios.json").read_text()):
        EvaluationRequest.model_validate(s["request"])


def test_card_present_without_device_metadata_scores_zero() -> None:
    t = txn("coffee")
    assert prescreen(t, BASELINES.get(t.user_id), POLICY).score == 0.0


def test_remote_without_device_metadata_is_partially_suspicious() -> None:
    t = txn("auto_parts_deadlock", metadata={})
    sig = prescreen(t, BASELINES.get(t.user_id), POLICY).signals
    assert sig["new_device"] == sig["new_ip"] == 0.5

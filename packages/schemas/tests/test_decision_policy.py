from decimal import Decimal

import pytest

from subpoena_schemas import (
    Channel,
    EvaluationStatus,
    Outcome,
    Policy,
    TestimonyOutcome,
    Verdict,
    WitnessAuthResult,
    decide,
    decide_after_testimony,
)

POLICY = Policy(workspace_id="ws_test")
WA = [Channel.WHATSAPP]
BIG = Decimal("4500.00")


def test_every_p_fraud_maps_to_exactly_one_outcome() -> None:
    for i in range(0, 101):
        p = i / 100
        d = decide(p, policy=POLICY, amount=BIG, witness_channels=WA)
        if p >= 0.85:
            assert d.outcome is Outcome.BLOCK and d.verdict is Verdict.BLOCK
        elif p <= 0.15:
            assert d.outcome is Outcome.APPROVE and d.verdict is Verdict.APPROVE
        else:
            assert d.outcome is Outcome.SUBPOENA and d.verdict is None
            assert d.status is EvaluationStatus.AWAITING_TESTIMONY


@pytest.mark.parametrize(
    ("p", "amount", "channels", "expected"),
    [
        (0.15, BIG, WA, Outcome.APPROVE),
        (0.1501, BIG, WA, Outcome.SUBPOENA),
        (0.8499, BIG, WA, Outcome.SUBPOENA),
        (0.85, BIG, WA, Outcome.BLOCK),
        (0.52, BIG, [], Outcome.ESCALATE),
        (0.52, Decimal("10.00"), WA, Outcome.ESCALATE),
        (0.52, BIG, [Channel.VOICE], Outcome.ESCALATE),  # not in policy channels
        (0.0, Decimal("1.00"), [], Outcome.APPROVE),
        (1.0, Decimal("1.00"), [], Outcome.BLOCK),
    ],
)
def test_boundaries(p: float, amount: Decimal, channels: list[Channel], expected: Outcome) -> None:
    assert decide(p, policy=POLICY, amount=amount, witness_channels=channels).outcome is expected


def test_escalate_holds_transaction() -> None:
    d = decide(0.5, policy=POLICY, amount=BIG, witness_channels=[])
    assert d.verdict is Verdict.HOLD and d.status is EvaluationStatus.ESCALATED


@pytest.mark.parametrize("p", [-0.01, 1.01])
def test_out_of_range_rejected(p: float) -> None:
    with pytest.raises(ValueError):
        decide(p, policy=POLICY, amount=BIG, witness_channels=WA)


def test_custom_thresholds_are_respected() -> None:
    policy = Policy.model_validate(
        {"workspace_id": "ws", "thresholds": {"approve_max": 0.3, "block_min": 0.6}}
    )
    assert decide(0.25, policy=policy, amount=BIG, witness_channels=WA).outcome is Outcome.APPROVE
    assert decide(0.65, policy=policy, amount=BIG, witness_channels=WA).outcome is Outcome.BLOCK


def test_auth_failure_blocks_and_escalates() -> None:
    d = decide_after_testimony(
        policy=POLICY,
        auth=WitnessAuthResult.FAILED,
        outcome=TestimonyOutcome.CONFIRMED,
        p_fraud_rerule=0.01,
    )
    assert d.verdict is Verdict.BLOCK and d.status is EvaluationStatus.ESCALATED


def test_denial_blocks_and_reissues() -> None:
    d = decide_after_testimony(
        policy=POLICY, auth=WitnessAuthResult.PASSED, outcome=TestimonyOutcome.DENIED
    )
    assert d.verdict is Verdict.BLOCK and d.reissue_card and d.status is EvaluationStatus.RULED


@pytest.mark.parametrize(
    ("p", "expected"),
    [(0.08, Verdict.APPROVE), (0.15, Verdict.APPROVE), (0.16, Verdict.HOLD), (0.95, Verdict.HOLD)],
)
def test_confirmation_rerule(p: float, expected: Verdict) -> None:
    for auth in (WitnessAuthResult.PASSED, WitnessAuthResult.SKIPPED_BY_POLICY):
        d = decide_after_testimony(
            policy=POLICY, auth=auth, outcome=TestimonyOutcome.CONFIRMED, p_fraud_rerule=p
        )
        assert d.verdict is expected


def test_confirmation_requires_rerule() -> None:
    with pytest.raises(ValueError):
        decide_after_testimony(
            policy=POLICY, auth=WitnessAuthResult.PASSED, outcome=TestimonyOutcome.CONFIRMED
        )


@pytest.mark.parametrize(
    ("action", "status"),
    [
        (Verdict.HOLD, EvaluationStatus.ESCALATED),
        (Verdict.APPROVE, EvaluationStatus.RULED),
        (Verdict.BLOCK, EvaluationStatus.RULED),
    ],
)
def test_timeout_applies_policy_action(action: Verdict, status: EvaluationStatus) -> None:
    policy = Policy.model_validate({"workspace_id": "ws", "subpoena": {"timeout_action": action}})
    d = decide_after_testimony(policy=policy, auth=None, outcome=TestimonyOutcome.NO_REPLY)
    assert d.verdict is action and d.status is status

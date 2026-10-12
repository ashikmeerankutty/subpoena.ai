"""Tenant policy and the decision policy from Spec §5.

``decide`` and ``decide_after_testimony`` are pure functions: every input maps to
exactly one ``Decision``. Thresholds come from the ``Policy`` document, never constants.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from .common import Channel, EvaluationStatus, Model, Verdict, new_id
from .subpoena import WitnessAuthResult


class Thresholds(Model):
    approve_max: float = Field(default=0.15, ge=0, le=1, description="p_fraud <= this -> APPROVE")
    block_min: float = Field(default=0.85, ge=0, le=1, description="p_fraud >= this -> BLOCK")

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if self.approve_max >= self.block_min:
            raise ValueError("approve_max must be below block_min")
        return self


class Tier0Thresholds(Model):
    approve_max: float = Field(default=0.30, ge=0, le=1, description="score <= this exits APPROVE")
    block_min: float = Field(default=0.97, ge=0, le=1, description="score >= this exits BLOCK")


class SubpoenaRules(Model):
    min_amount: Decimal = Field(default=Decimal("50.00"), ge=0)
    channels: list[Channel] = Field(default_factory=lambda: [Channel.WHATSAPP, Channel.SMS])
    timeout_seconds: int = Field(default=900, gt=0)
    timeout_action: Verdict = Verdict.HOLD


class HardRules(Model):
    sanctioned_countries: list[str] = Field(default_factory=lambda: ["KP", "IR", "CU", "SY"])
    known_bad_devices: list[str] = Field(default_factory=list)
    known_bad_ips: list[str] = Field(default_factory=list)
    amount_ceiling: Decimal | None = Field(default=Decimal("50000.00"))


class Policy(Model):
    id: str = Field(default_factory=lambda: new_id("pol"))
    workspace_id: str
    version: int = Field(default=1, ge=1)
    active: bool = True
    thresholds: Thresholds = Field(default_factory=Thresholds)
    tier0: Tier0Thresholds = Field(default_factory=Tier0Thresholds)
    subpoena: SubpoenaRules = Field(default_factory=SubpoenaRules)
    hard_rules: HardRules = Field(default_factory=HardRules)


class Outcome(StrEnum):
    APPROVE = "APPROVE"
    BLOCK = "BLOCK"
    SUBPOENA = "SUBPOENA"
    ESCALATE = "ESCALATE"


class Decision(Model):
    outcome: Outcome
    verdict: Verdict | None
    status: EvaluationStatus
    reason: str
    reissue_card: bool = False


class TestimonyOutcome(StrEnum):
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    NO_REPLY = "NO_REPLY"


def _approve(reason: str) -> Decision:
    return Decision(
        outcome=Outcome.APPROVE,
        verdict=Verdict.APPROVE,
        status=EvaluationStatus.RULED,
        reason=reason,
    )


def _block(reason: str, *, escalate: bool = False, reissue_card: bool = False) -> Decision:
    return Decision(
        outcome=Outcome.ESCALATE if escalate else Outcome.BLOCK,
        verdict=Verdict.BLOCK,
        status=EvaluationStatus.ESCALATED if escalate else EvaluationStatus.RULED,
        reason=reason,
        reissue_card=reissue_card,
    )


def _escalate(reason: str, verdict: Verdict = Verdict.HOLD) -> Decision:
    return Decision(
        outcome=Outcome.ESCALATE, verdict=verdict, status=EvaluationStatus.ESCALATED, reason=reason
    )


def _check_p(p_fraud: float) -> None:
    if not 0.0 <= p_fraud <= 1.0:
        raise ValueError(f"p_fraud must be in [0, 1], got {p_fraud}")


def decide(
    p_fraud: float, *, policy: Policy, amount: Decimal, witness_channels: list[Channel]
) -> Decision:
    """Map the Judge's first ruling to an outcome (Spec §5, first table)."""
    _check_p(p_fraud)
    t = policy.thresholds
    if p_fraud >= t.block_min:
        return _block(f"p_fraud {p_fraud:.2f} >= block threshold {t.block_min:.2f}")
    if p_fraud <= t.approve_max:
        return _approve(f"p_fraud {p_fraud:.2f} <= approve threshold {t.approve_max:.2f}")
    usable = [c for c in policy.subpoena.channels if c in witness_channels]
    if usable and amount >= policy.subpoena.min_amount:
        return Decision(
            outcome=Outcome.SUBPOENA,
            verdict=None,
            status=EvaluationStatus.AWAITING_TESTIMONY,
            reason=(
                f"Evidentiary deadlock at p_fraud {p_fraud:.2f}; witness reachable via {usable[0]}"
            ),
        )
    why = "no witness channel allowed by policy" if not usable else "amount below subpoena minimum"
    return _escalate(f"Deadlock at p_fraud {p_fraud:.2f}; {why}")


def decide_after_testimony(
    *,
    policy: Policy,
    auth: WitnessAuthResult | None,
    outcome: TestimonyOutcome,
    p_fraud_rerule: float | None = None,
) -> Decision:
    """Map a subpoena's result to a final outcome (Spec §5, "After testimony")."""
    if outcome is TestimonyOutcome.NO_REPLY:
        action = policy.subpoena.timeout_action
        if action is Verdict.APPROVE:
            return _approve("No reply before subpoena timeout; policy timeout_action is APPROVE")
        if action is Verdict.BLOCK:
            return _block("No reply before subpoena timeout; policy timeout_action is BLOCK")
        return _escalate("No reply before subpoena timeout; held for analyst review")
    if auth is WitnessAuthResult.FAILED:
        return _block("Witness authentication failed (possible account takeover)", escalate=True)
    if outcome is TestimonyOutcome.DENIED:
        return _block("Cardholder denied the transaction", reissue_card=True)
    if p_fraud_rerule is None:
        raise ValueError("p_fraud_rerule is required when the witness confirms")
    _check_p(p_fraud_rerule)
    if p_fraud_rerule <= policy.thresholds.approve_max:
        return _approve(f"Witness confirmed; re-ruled p_fraud {p_fraud_rerule:.2f}")
    return _escalate(f"Witness confirmed but re-ruled p_fraud {p_fraud_rerule:.2f} still elevated")

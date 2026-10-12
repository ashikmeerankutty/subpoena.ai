"""Evaluation (case) resource returned by the API (Spec §8, §9)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .common import Agent, EvaluationStatus, Model, Verdict, new_id, utcnow
from .finding import EvidenceFinding
from .subpoena import SubpoenaRef, Testimony
from .transaction import EvaluationOptions, Transaction, Witness


class Tier0Route(StrEnum):
    EXIT_APPROVE = "EXIT_APPROVE"
    EXIT_BLOCK = "EXIT_BLOCK"
    COURT = "COURT"


class Tier0Result(Model):
    score: float = Field(ge=0, le=1)
    route: Tier0Route
    rules_hit: list[str] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)
    latency_ms: float = Field(ge=0)


class DebateSummaryItem(Model):
    agent: Agent
    position: Verdict
    summary: str


class Links(Model):
    self: str
    events: str


class Evaluation(Model):
    evaluation_id: str = Field(default_factory=lambda: new_id("eval"))
    workspace_id: str
    transaction: Transaction
    witness: Witness | None = None
    options: EvaluationOptions = Field(default_factory=EvaluationOptions)
    status: EvaluationStatus = EvaluationStatus.RECEIVED
    p_fraud: float | None = Field(default=None, ge=0, le=1)
    verdict: Verdict | None = None
    rationale: str | None = None
    explanation: str | None = None
    policy_version: int
    tier0: Tier0Result | None = None
    findings: list[EvidenceFinding] = Field(default_factory=list)
    debate_summary: list[DebateSummaryItem] = Field(default_factory=list)
    subpoena: SubpoenaRef | None = None
    testimony: Testimony | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    ruled_at: datetime | None = None
    cost_usd: float | None = Field(default=None, description="Model cost of the courtroom run")
    tokens: int | None = None
    override: dict[str, Any] | None = None

    @property
    def links(self) -> Links:
        base = f"/v1/evaluations/{self.evaluation_id}"
        return Links(self=base, events=f"{base}/events")


class EvaluationResponse(Model):
    """Public shape of an evaluation (drops internal fields such as workspace_id)."""

    evaluation_id: str
    transaction_id: str
    user_id: str
    status: EvaluationStatus
    p_fraud: float | None
    verdict: Verdict | None
    rationale: str | None = None
    explanation: str | None = None
    policy_version: int
    tier0: Tier0Result | None = None
    findings: list[EvidenceFinding] = Field(default_factory=list)
    debate_summary: list[DebateSummaryItem] = Field(default_factory=list)
    subpoena: SubpoenaRef | None = None
    testimony: Testimony | None = None
    created_at: datetime
    updated_at: datetime
    ruled_at: datetime | None = None
    cost_usd: float | None = None
    tokens: int | None = None
    override: dict[str, Any] | None = None
    amount: str
    currency: str
    merchant: str
    occurred_at: datetime
    links: Links

    @classmethod
    def from_evaluation(cls, ev: Evaluation) -> EvaluationResponse:
        return cls(
            evaluation_id=ev.evaluation_id,
            transaction_id=ev.transaction.transaction_id,
            user_id=ev.transaction.user_id,
            status=ev.status,
            p_fraud=ev.p_fraud,
            verdict=ev.verdict,
            rationale=ev.rationale,
            explanation=ev.explanation,
            policy_version=ev.policy_version,
            tier0=ev.tier0,
            findings=ev.findings,
            debate_summary=ev.debate_summary,
            subpoena=ev.subpoena,
            testimony=ev.testimony,
            created_at=ev.created_at,
            updated_at=ev.updated_at,
            ruled_at=ev.ruled_at,
            cost_usd=ev.cost_usd,
            tokens=ev.tokens,
            override=ev.override,
            amount=str(ev.transaction.amount),
            currency=ev.transaction.currency,
            merchant=ev.transaction.merchant.name,
            occurred_at=ev.transaction.occurred_at,
            links=ev.links,
        )


class PageMeta(Model):
    next_page_token: str | None = None


class Page[T](BaseModel):
    data: list[T]
    meta: PageMeta

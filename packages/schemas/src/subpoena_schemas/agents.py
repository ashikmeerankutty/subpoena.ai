"""Structured outputs of the courtroom agents (Gemini response schemas).

These are plain ``BaseModel``s (no ``extra=forbid``) so they translate cleanly to the
response-schema subset Gemini accepts. IDs (F1, F2, ...) are assigned by code, not models.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExpertFindingOut(BaseModel):
    type: str = Field(description="UPPER_SNAKE signal name, e.g. NEW_DEVICE, IMPOSSIBLE_TRAVEL")
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    supports: Literal["FRAUD", "LEGIT", "NEUTRAL"]
    detail: str = Field(description="One factual sentence grounded in the provided data")


class ExpertReport(BaseModel):
    findings: list[ExpertFindingOut] = Field(description="1-4 findings in this domain only")


class ClaimOut(BaseModel):
    text: str = Field(description="One argument sentence")
    cites: list[str] = Field(description="Finding IDs (F1..) or precedent IDs (P1..) it rests on")


class ArgumentOut(BaseModel):
    claims: list[ClaimOut] = Field(description="2-4 claims, strongest first")
    summary: str = Field(description="One-sentence summary of the position")


class RulingOut(BaseModel):
    p_fraud: float = Field(
        ge=0, le=1, description="Calibrated probability the transaction is fraud"
    )
    confidence: float = Field(ge=0, le=1, description="Confidence in this estimate")
    rationale: str = Field(description="2-3 sentences weighing both sides")
    cited_findings: list[str] = Field(description="Finding IDs that drove the ruling")
    subpoena_question: str | None = Field(
        default=None,
        description="If evidence is deadlocked: one short yes/no question for the cardholder "
        "targeting the specific uncertainty. Never ask for passwords, PINs or codes.",
    )


class ExplanationOut(BaseModel):
    bank_explanation: str = Field(
        description="Plain-language explanation for the bank, 2-3 sentences"
    )
    cardholder_notice: str = Field(description="Short, friendly notice for the cardholder")
    sar_draft: str | None = Field(
        default=None, description="Suspicious Activity Report narrative, only when blocked"
    )

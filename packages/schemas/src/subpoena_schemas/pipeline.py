"""Agent-to-agent messages persisted for the Pipeline view (Spec §4)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import Agent, Model, new_id, utcnow


class EventType(StrEnum):
    CASE_OPENED = "CASE_OPENED"
    TOOL_CALL = "TOOL_CALL"
    FINDING = "FINDING"
    ARGUMENT = "ARGUMENT"
    REBUTTAL = "REBUTTAL"
    CLAIM_STRUCK = "CLAIM_STRUCK"
    RULING = "RULING"
    SUBPOENA_SENT = "SUBPOENA_SENT"
    WITNESS_AUTH = "WITNESS_AUTH"
    TESTIMONY = "TESTIMONY"
    VERDICT = "VERDICT"
    OVERRIDE = "OVERRIDE"
    ERROR = "ERROR"


class TokenUsage(Model):
    input: int = Field(ge=0)
    output: int = Field(ge=0)


class Claim(Model):
    text: str
    cites: list[str] = Field(default_factory=list)


class PipelineEvent(Model):
    event_id: str = Field(default_factory=lambda: new_id("pev"))
    evaluation_id: str
    sequence: int = Field(ge=0)
    round: int | None = Field(default=None, ge=0)
    from_agent: Agent
    to_agent: Agent | None = None
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    tokens: TokenUsage | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=utcnow)

"""Evidence produced by Expert Witnesses (Spec §4, §9)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .common import Agent, Model


class Severity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EvidenceFinding(Model):
    id: str = Field(pattern=r"^F\d+$", description="Citable finding ID, e.g. F2")
    agent: Agent
    type: str = Field(description="Machine-readable signal, e.g. NEW_DEVICE, AMOUNT_SPIKE")
    severity: Severity
    supports: str = Field(pattern=r"^(FRAUD|LEGIT|NEUTRAL)$")
    detail: str
    source_ref: str | None = Field(default=None, description="MCP resource/tool that produced it")

"""Precedents: past rulings retrieved as case law (Spec §15 "stare decisis", §10 Precedents)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .common import Model, new_id, utcnow


class PrecedentSource(StrEnum):
    SEED = "SEED"  # shipped library
    CASE = "CASE"  # a courtroom ruling in this workspace
    OVERRIDE = "OVERRIDE"  # an analyst's corrected ruling


class Precedent(Model):
    id: str = Field(default_factory=lambda: new_id("prec"))
    workspace_id: str | None = Field(default=None, description="None for the shared seed library")
    summary: str = Field(description="Case in plain words; this text is embedded for search")
    verdict: str
    label: str = Field(description="FRAUD or LEGIT")
    tags: list[str] = Field(default_factory=list)
    source: PrecedentSource = PrecedentSource.CASE
    evaluation_id: str | None = None
    embedding: list[float] | None = Field(default=None, description="Never returned by the API")
    embedding_model: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @staticmethod
    def id_for(evaluation_id: str) -> str:
        return f"prec_{evaluation_id.removeprefix('eval_')}"

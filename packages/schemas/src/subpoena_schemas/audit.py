"""Append-only audit trail of human and system actions (Spec §9 AuditLog, §10 Audit Log)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import Model, new_id, utcnow
from .workspace import ApiKey, KeyKind


class ActorType(StrEnum):
    API_KEY = "API_KEY"
    MEMBER = "MEMBER"
    SYSTEM = "SYSTEM"


class Actor(Model):
    type: ActorType
    id: str | None = None
    name: str

    @classmethod
    def of(cls, key: ApiKey) -> Actor:
        if key.kind is KeyKind.SESSION:
            return cls(type=ActorType.MEMBER, id=key.member_id, name=key.name)
        return cls(type=ActorType.API_KEY, id=key.id, name=f"{key.name} ({key.prefix}…)")


class AuditEntry(Model):
    id: str = Field(default_factory=lambda: new_id("aud"))
    workspace_id: str
    actor: Actor
    action: str = Field(description="dotted verb, e.g. policy.published, evaluation.overridden")
    target: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    at: datetime = Field(default_factory=utcnow)

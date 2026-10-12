"""Workspaces, API keys and sources (Spec §9)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .common import Model, new_id, utcnow


class Scope(StrEnum):
    EVALUATIONS_WRITE = "evaluations:write"
    EVALUATIONS_READ = "evaluations:read"
    EVALUATIONS_OVERRIDE = "evaluations:override"
    ADMIN = "admin"


class Workspace(Model):
    id: str = Field(default_factory=lambda: new_id("ws"))
    name: str
    region: str = "us-central1"
    plan: str = "hackathon"
    created_at: datetime = Field(default_factory=utcnow)


class ApiKey(Model):
    id: str = Field(default_factory=lambda: new_id("key"))
    workspace_id: str
    name: str
    prefix: str = Field(description="First characters of the secret, safe to display")
    hash: str = Field(description="HMAC-SHA256 of the secret; the secret itself is never stored")
    scopes: list[Scope]
    created_by: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyPublic(Model):
    id: str
    name: str
    prefix: str
    scopes: list[Scope]
    created_by: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_key(cls, key: ApiKey) -> ApiKeyPublic:
        return cls.model_validate(key.model_dump(exclude={"workspace_id", "hash"}))


class ApiKeyCreated(ApiKeyPublic):
    secret: str = Field(description="Shown exactly once")


class SourceType(StrEnum):
    REST = "REST"
    PUBSUB = "PUBSUB"
    BIGQUERY_STREAM = "BIGQUERY_STREAM"


class Source(Model):
    id: str = Field(default_factory=lambda: new_id("src"))
    workspace_id: str
    name: str
    type: SourceType = SourceType.REST
    api_key_ids: list[str] = Field(default_factory=list)
    health: str = "UNKNOWN"
    created_at: datetime = Field(default_factory=utcnow)

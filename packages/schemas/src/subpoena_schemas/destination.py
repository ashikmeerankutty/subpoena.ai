"""Destinations: where a workspace's decisions are delivered (Spec §9 Destination, §10)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .common import Model, new_id, utcnow

EVENT_TYPES = (
    "evaluation.completed",
    "evaluation.escalated",
    "evaluation.overridden",
    "subpoena.sent",
    "subpoena.expired",
    "testimony.received",
    "witness_auth.failed",
)


class DestinationType(StrEnum):
    WEBHOOK = "WEBHOOK"
    SLACK = "SLACK"
    PUBSUB = "PUBSUB"
    BIGQUERY = "BIGQUERY"


class Destination(Model):
    id: str = Field(default_factory=lambda: new_id("dst"))
    workspace_id: str
    name: str = Field(min_length=1, max_length=100)
    type: DestinationType
    config: dict[str, str] = Field(
        description="WEBHOOK/SLACK: url · PUBSUB: topic (projects/../topics/..) · "
        "BIGQUERY: table (project.dataset.table)"
    )
    enabled_events: list[str] = Field(
        default_factory=list, description="Event types to deliver; empty means all"
    )
    enabled: bool = True
    created_by: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    def wants(self, event_type: str) -> bool:
        return self.enabled and (
            not self.enabled_events
            or event_type in self.enabled_events
            or event_type == "destination.test"
        )


class DeliveryStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Delivery(Model):
    """One delivery of one event to one destination, after retries."""

    id: str = Field(default_factory=lambda: new_id("dlv"))
    workspace_id: str
    destination_id: str
    event_id: str
    event_type: str
    evaluation_id: str | None = None
    status: DeliveryStatus
    attempts: int = Field(ge=1)
    response_code: int | None = None
    error: str | None = None
    latency_ms: int = Field(ge=0)
    at: datetime = Field(default_factory=utcnow)

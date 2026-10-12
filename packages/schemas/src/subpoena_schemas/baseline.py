"""User behavioural baselines (MCP ``user_profile://{user_id}/baselines``)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from .common import Model


class GeoPoint(Model):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    city: str | None = None
    country: str = Field(pattern=r"^[A-Z]{2}$")


class UserBaseline(Model):
    user_id: str
    home: GeoPoint
    utc_offset_hours: int = Field(default=0, ge=-12, le=14)
    known_devices: list[str] = Field(default_factory=list)
    known_ips: list[str] = Field(default_factory=list)
    avg_amount: Decimal
    p95_amount: Decimal
    txn_per_day: float = Field(ge=0)
    active_hours: list[int] = Field(default_factory=list, description="Local hours with activity")
    common_mccs: list[str] = Field(default_factory=list)
    window_days: int = 90
    computed_at: datetime

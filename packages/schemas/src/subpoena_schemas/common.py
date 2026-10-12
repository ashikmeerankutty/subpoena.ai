"""Enums, identifiers and base model shared by every schema."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

_ID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def new_id(prefix: str, length: int = 16) -> str:
    """Return a random, URL-safe identifier such as ``eval_9f2k...``."""
    return f"{prefix}_" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


def utcnow() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    """Base for all schemas: forbids unknown fields so payload drift fails loudly."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvaluationStatus(StrEnum):
    RECEIVED = "RECEIVED"
    IN_DEBATE = "IN_DEBATE"
    AWAITING_TESTIMONY = "AWAITING_TESTIMONY"
    RULED = "RULED"
    ESCALATED = "ESCALATED"
    APPEALED = "APPEALED"


class Verdict(StrEnum):
    APPROVE = "APPROVE"
    BLOCK = "BLOCK"
    HOLD = "HOLD"


class TransactionType(StrEnum):
    CARD_PRESENT = "CARD_PRESENT"
    CARD_NOT_PRESENT = "CARD_NOT_PRESENT"
    P2P = "P2P"
    WIRE = "WIRE"
    ACH = "ACH"


class Channel(StrEnum):
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"
    VOICE = "VOICE"
    PUSH = "PUSH"


class Agent(StrEnum):
    SYSTEM = "system"
    CLERK = "clerk"
    GEO = "geo"
    DEVICE = "device"
    VELOCITY = "velocity"
    MERCHANT = "merchant"
    GRAPH = "graph"
    PROSECUTOR = "prosecutor"
    DEFENSE = "defense"
    JUDGE = "judge"
    BAILIFF = "bailiff"
    STENOGRAPHER = "stenographer"
    WITNESS = "witness"
    ANALYST = "analyst"


class Role(StrEnum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"

"""Subpoena, witness authentication and testimony (Spec §6, §9)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .common import Channel, Model, new_id, utcnow


class DeliveryStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"
    UNDELIVERED = "UNDELIVERED"


class WitnessAuthResult(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED_BY_POLICY = "SKIPPED_BY_POLICY"


class SubpoenaState(StrEnum):
    """Lifecycle of one subpoena, driven by the Bailiff and inbound messages."""

    AUTH_FAILED = "AUTH_FAILED"  # Lookup failed before sending; witness never contacted
    AWAITING_REPLY = "AWAITING_REPLY"  # question + one-time code sent
    ADMITTED = "ADMITTED"  # reply received and code verified; testimony admitted
    CODE_FAILED = "CODE_FAILED"  # too many wrong codes
    EXPIRED = "EXPIRED"  # no admissible testimony before expires_at


class SubpoenaRef(Model):
    id: str
    channel: Channel
    sent_at: datetime
    expires_at: datetime


class MediaRef(Model):
    """A photo the witness sent. Bytes live in the media store under ``{workspace_id}/{id}``."""

    id: str = Field(default_factory=lambda: new_id("med"))
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    source: str = Field(description="twilio | simulator")


class ReceiptResult(StrEnum):
    MATCH = "MATCH"  # merchant and amount match (date too, when visible)
    PARTIAL = "PARTIAL"  # some fields match, others not visible
    MISMATCH = "MISMATCH"  # a visible field contradicts the transaction
    NOT_A_RECEIPT = "NOT_A_RECEIPT"
    UNREADABLE = "UNREADABLE"


class ReceiptCheck(Model):
    """Deterministic comparison of an extracted receipt with the transaction (Spec §6 step 5)."""

    media_id: str
    result: ReceiptResult
    merchant: str | None = None
    amount: str | None = None
    currency: str | None = None
    date: str | None = None
    order_reference: str | None = None
    merchant_match: bool | None = None
    amount_match: bool | None = None
    date_match: bool | None = None
    reasons: list[str] = Field(default_factory=list)


class Subpoena(SubpoenaRef):
    id: str = Field(default_factory=lambda: new_id("sbp"))
    workspace_id: str
    evaluation_id: str
    user_id: str
    phone: str
    question: str
    state: SubpoenaState = SubpoenaState.AWAITING_REPLY
    twilio_sid: str | None = None
    delivery_status: DeliveryStatus = DeliveryStatus.QUEUED
    lookup: dict[str, object] = Field(default_factory=dict, description="Lookup result")
    reply_text: str | None = None
    pending_code: str | None = Field(default=None, description="Code awaiting a Bailiff check")
    code_verified: bool = False
    code_attempts: int = 0
    responded_at: datetime | None = None
    media: list[MediaRef] = Field(default_factory=list, description="Photos sent by the witness")

    def ref(self) -> SubpoenaRef:
        return SubpoenaRef(
            id=self.id, channel=self.channel, sent_at=self.sent_at, expires_at=self.expires_at
        )


class TestimonyClaims(BaseModel):
    """Structured output of the tool-less extractor. Never contains instructions."""

    confirms_transaction: bool | None = Field(
        description="true if the witness says they made it, false if not, null if unclear"
    )
    stated_reason: str | None = Field(default=None, description="Why, in the witness's words")
    mentions_travel: bool = False
    sentiment: str | None = Field(default=None, description="calm, anxious, angry, ...")


class Testimony(Model):
    subpoena_id: str
    raw_text: str = Field(description="Redacted; untrusted content")
    claims: TestimonyClaims
    media_refs: list[str] = Field(default_factory=list)
    receipt: ReceiptCheck | None = None
    witness_auth_result: WitnessAuthResult
    flagged_by_screening: bool = False
    screening_reasons: list[str] = Field(default_factory=list)
    received_at: datetime


class MessageDirection(StrEnum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


class WitnessMessage(Model):
    """One message in the witness conversation (mirrored WhatsApp view in the Console)."""

    id: str = Field(default_factory=lambda: new_id("msg"))
    workspace_id: str | None = None
    subpoena_id: str | None = None
    evaluation_id: str | None = None
    phone: str
    direction: MessageDirection
    channel: Channel
    body: str
    sid: str | None = None
    status: DeliveryStatus = DeliveryStatus.QUEUED
    media: list[MediaRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

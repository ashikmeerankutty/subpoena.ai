"""Inbound evaluation request (Spec §8 ``POST /v1/evaluations``)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, HttpUrl

from .common import Channel, Model, TransactionType


class Merchant(Model):
    name: str = Field(min_length=1, max_length=200)
    mcc: str = Field(pattern=r"^\d{4}$", description="ISO 18245 merchant category code")
    country: str = Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2")


class TransactionMetadata(Model):
    ip_address: str | None = None
    device_fingerprint: str | None = None
    user_agent: str | None = None


class Witness(Model):
    phone: str = Field(pattern=r"^\+[1-9]\d{6,14}$", description="E.164 phone number")
    allowed_channels: list[Channel] = Field(default_factory=lambda: [Channel.WHATSAPP, Channel.SMS])
    locale: str = "en-US"


class EvaluationOptions(Model):
    sync_timeout_ms: int = Field(default=8000, ge=0, le=30000)
    callback_url: HttpUrl | None = None


class Transaction(Model):
    transaction_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    type: TransactionType
    occurred_at: datetime
    merchant: Merchant
    metadata: TransactionMetadata = Field(default_factory=TransactionMetadata)


class EvaluationRequest(Transaction):
    witness: Witness | None = None
    options: EvaluationOptions = Field(default_factory=EvaluationOptions)

    def transaction(self) -> Transaction:
        return Transaction.model_validate(self.model_dump(exclude={"witness", "options"}))

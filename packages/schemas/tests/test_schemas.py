import pytest
from pydantic import ValidationError

from subpoena_schemas import EvaluationRequest, Thresholds

SPEC_EXAMPLE = {
    "transaction_id": "tx_8839201",
    "user_id": "usr_9921",
    "amount": 4500.00,
    "currency": "USD",
    "type": "CARD_NOT_PRESENT",
    "occurred_at": "2026-10-09T02:14:03Z",
    "merchant": {"name": "AutoZone Online", "mcc": "5533", "country": "US"},
    "metadata": {
        "ip_address": "203.0.113.44",
        "device_fingerprint": "abc-123",
        "user_agent": "Mozilla/5.0",
    },
    "witness": {
        "phone": "+14155550123",
        "allowed_channels": ["WHATSAPP", "SMS"],
        "locale": "en-US",
    },
    "options": {"sync_timeout_ms": 8000, "callback_url": "https://bank.example.com/hooks/subpoena"},
}


def test_spec_example_request_is_valid() -> None:
    req = EvaluationRequest.model_validate(SPEC_EXAMPLE)
    assert req.transaction().transaction_id == "tx_8839201"


@pytest.mark.parametrize(
    "patch",
    [{"amount": -1}, {"currency": "usd"}, {"unknown_field": 1}, {"type": "CASH"}],
)
def test_invalid_requests_rejected(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(SPEC_EXAMPLE | patch)


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        Thresholds(approve_max=0.9, block_min=0.5)

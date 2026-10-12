from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from courtkit import Harness
from subpoena_agents.receipts import compare, merchant_matches, parse_amount
from subpoena_schemas import (
    EvaluationStatus,
    MediaRef,
    Merchant,
    ReceiptOut,
    ReceiptResult,
    Transaction,
    TransactionType,
    Verdict,
)

TX = Transaction(
    transaction_id="tx_1",
    user_id="usr_1",
    amount=Decimal("4500.00"),
    currency="USD",
    type=TransactionType.CARD_NOT_PRESENT,
    occurred_at=datetime(2026, 10, 9, 9, 14, tzinfo=UTC),
    merchant=Merchant(name="AutoZone Online", mcc="5533", country="US"),
)


def seen(**fields: Any) -> ReceiptOut:
    blank = {
        "merchant": None,
        "amount": None,
        "currency": None,
        "date": None,
        "order_reference": None,
    }
    return ReceiptOut.model_validate({"is_receipt": True, **blank, **fields})


@pytest.mark.parametrize(
    ("fields", "result"),
    [
        (
            {"merchant": "AUTOZONE", "amount": "$4,500.00", "date": "2026-10-09"},
            ReceiptResult.MATCH,
        ),
        ({"merchant": "autozone.com", "amount": "4520.00", "currency": "USD"}, ReceiptResult.MATCH),
        ({"merchant": "AutoZone"}, ReceiptResult.PARTIAL),
        ({"merchant": "AutoZone", "amount": "45.00"}, ReceiptResult.MISMATCH),
        ({"merchant": "Best Buy", "amount": "4500.00"}, ReceiptResult.MISMATCH),
        ({"merchant": "AutoZone", "amount": "4500", "currency": "EUR"}, ReceiptResult.MISMATCH),
        ({"merchant": "AutoZone", "amount": "4500", "date": "2026-08-01"}, ReceiptResult.MISMATCH),
        ({}, ReceiptResult.UNREADABLE),
    ],
)
def test_compare(fields: dict[str, Any], result: ReceiptResult) -> None:
    check = compare("med_1", seen(**fields), TX)
    assert check.result is result, check.reasons


def test_not_a_receipt() -> None:
    out = ReceiptOut(
        is_receipt=False, merchant=None, amount=None, currency=None, date=None, order_reference=None
    )
    assert compare("med_1", out, TX).result is ReceiptResult.NOT_A_RECEIPT


def test_helpers() -> None:
    assert parse_amount("4.500,00") is None or parse_amount("4500,00") == Decimal("4500.00")
    assert parse_amount("USD 4,500.00") == Decimal("4500.00")
    assert merchant_matches("AUTOZONE #5521", "AutoZone Online")
    assert not merchant_matches("Online Store", "AutoZone Online")  # generic words don't count


async def _subpoena_with_photo(h: Harness, photo: bytes, ctype: str = "image/jpeg") -> Any:
    await h.setup()
    ev = await h.case("auto_parts_deadlock")
    ev = await h.court.run_case(ev.evaluation_id)
    assert ev.status is EvaluationStatus.AWAITING_TESTIMONY and ev.subpoena
    sub = await h.store.get_subpoena(ev.subpoena.id)
    assert sub is not None
    ref = MediaRef(
        content_type=ctype,
        size_bytes=len(photo),
        sha256=hashlib.sha256(photo).hexdigest(),
        source="simulator",
    )
    await h.court.media.put(f"{sub.workspace_id}/{ref.id}", photo, ctype)
    sub.media.append(ref)
    await h.store.put_subpoena(sub)
    await h.reply(sub.id, text="Yes, parts for my BMW E36 project")
    done = await h.reply(sub.id, code=await h.last_code("+14155550123"))
    return done, await h.store.list_events(done.evaluation_id)


def receipt_photo(**fields: Any) -> bytes:
    # The scripted backend reads receipt fields from JSON instead of pixels.
    return json.dumps(fields).encode()


def test_matching_receipt_is_admitted_as_evidence(h: Harness) -> None:
    ev, events = asyncio.run(
        _subpoena_with_photo(
            h, receipt_photo(merchant="AutoZone", amount="4,500.00", date="2026-10-09")
        )
    )
    assert ev.verdict is Verdict.APPROVE
    assert ev.testimony.receipt.result is ReceiptResult.MATCH
    assert ev.testimony.media_refs == [ev.testimony.receipt.media_id]
    kinds = [e.type.value for e in events]
    assert kinds[-4:] == ["TESTIMONY", "EVIDENCE", "RULING", "VERDICT"]
    evidence = next(e for e in events if e.type.value == "EVIDENCE")
    assert evidence.payload["result"] == "MATCH" and evidence.payload["amount_match"] is True


def test_mismatching_receipt_can_never_auto_approve(h: Harness) -> None:
    ev, _ = asyncio.run(_subpoena_with_photo(h, receipt_photo(merchant="Best Buy", amount="89.99")))
    assert ev.testimony.receipt.result is ReceiptResult.MISMATCH
    assert ev.status is EvaluationStatus.ESCALATED and ev.verdict is Verdict.HOLD


def test_unrelated_photo_adds_nothing(h: Harness) -> None:
    ev, _ = asyncio.run(_subpoena_with_photo(h, b"\xff\xd8\xff not json, a cat picture"))
    assert ev.testimony.receipt.result is ReceiptResult.NOT_A_RECEIPT
    assert ev.verdict is Verdict.APPROVE  # the confirmed testimony still stands

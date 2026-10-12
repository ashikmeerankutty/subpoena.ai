"""Receipt-photo evidence (Spec §6 step 5): compare what the photo shows with the transaction.

The vision model only *reads* the image (it never sees the transaction, so it cannot be led);
this module decides whether the receipt matches, deterministically.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from subpoena_schemas import ReceiptCheck, ReceiptOut, ReceiptResult, Transaction

AMOUNT_TOLERANCE = Decimal("0.01")  # 1% (taxes/rounding on order confirmations)
DATE_WINDOW_DAYS = 3
GENERIC = {
    "inc",
    "llc",
    "ltd",
    "co",
    "corp",
    "the",
    "online",
    "store",
    "shop",
    "com",
    "www",
    "and",
    "company",
    "limited",
    "gmbh",
    "plc",
    "pvt",
}


def _tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    return {w for w in words if len(w) >= 3 and w not in GENERIC}


def merchant_matches(seen: str, expected: str) -> bool:
    a, b = _tokens(seen), _tokens(expected)
    if not a or not b:
        return False
    x, y = _squash(seen), _squash(expected)
    return bool(a & b) or x in y or y in x


def _squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_amount(text: str) -> Decimal | None:
    cleaned = re.sub(r"[^\d.,-]", "", text)
    if cleaned.count(",") and cleaned.count("."):
        cleaned = cleaned.replace(",", "")  # 4,500.00
    elif cleaned.count(",") == 1 and len(cleaned.split(",")[1]) == 2:
        cleaned = cleaned.replace(",", ".")  # 4500,00
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def compare(media_id: str, seen: ReceiptOut, tx: Transaction) -> ReceiptCheck:
    check = ReceiptCheck(
        media_id=media_id,
        result=ReceiptResult.UNREADABLE,
        merchant=seen.merchant,
        amount=seen.amount,
        currency=seen.currency,
        date=seen.date,
        order_reference=seen.order_reference,
    )
    if not seen.is_receipt:
        check.result = ReceiptResult.NOT_A_RECEIPT
        check.reasons.append("The photo is not a receipt or order confirmation")
        return check

    if seen.merchant:
        check.merchant_match = merchant_matches(seen.merchant, tx.merchant.name)
        if not check.merchant_match:
            check.reasons.append(f"Merchant on receipt '{seen.merchant}' ≠ '{tx.merchant.name}'")
    if seen.amount:
        amount = parse_amount(seen.amount)
        if amount is None:
            check.reasons.append(f"Amount '{seen.amount}' is not readable")
        elif seen.currency and seen.currency.upper() != tx.currency:
            check.amount_match = False
            check.reasons.append(f"Currency on receipt {seen.currency} ≠ {tx.currency}")
        else:
            check.amount_match = abs(amount - tx.amount) <= max(
                Decimal("0.01"), tx.amount * AMOUNT_TOLERANCE
            )
            if not check.amount_match:
                check.reasons.append(f"Total on receipt {amount} ≠ transaction {tx.amount}")
    if seen.date:
        try:
            day = date.fromisoformat(seen.date)
        except ValueError:
            check.reasons.append(f"Date '{seen.date}' is not readable")
        else:
            check.date_match = abs((day - tx.occurred_at.date()).days) <= DATE_WINDOW_DAYS
            if not check.date_match:
                check.reasons.append(f"Receipt date {day} is far from {tx.occurred_at.date()}")

    visible = [
        m for m in (check.merchant_match, check.amount_match, check.date_match) if m is not None
    ]
    if not visible:
        check.result = ReceiptResult.UNREADABLE
        check.reasons.append("Neither merchant nor amount could be read")
    elif False in visible:
        check.result = ReceiptResult.MISMATCH
    elif check.merchant_match and check.amount_match:
        check.result = ReceiptResult.MATCH
    else:
        check.result = ReceiptResult.PARTIAL
        check.reasons.append("Only part of the receipt could be matched")
    return check

"""Tier 0 pre-screen (Spec §1, §5): hard rules plus a fast heuristic score.

Clear approvals and hard-rule blocks exit here; everything ambiguous goes to court.
The score is a noisy-OR over weighted signals in [0, 1], so each signal can only raise risk
and no single weak signal dominates. It is a placeholder for the BigQuery ML model.
"""

from __future__ import annotations

import time
from datetime import timedelta
from decimal import Decimal

from subpoena_schemas import (
    Policy,
    Tier0Result,
    Tier0Route,
    Transaction,
    TransactionType,
    UserBaseline,
)

WEIGHTS: dict[str, float] = {
    "amount_spike": 0.60,
    "new_device": 0.35,
    "new_ip": 0.20,
    "odd_hour": 0.15,
    "mcc_risk": 0.30,
    "remote_channel": 0.10,
    "foreign_merchant": 0.30,
    "no_baseline": 0.40,
}

# Relative risk by MCC (0 = ordinary). Unlisted codes are treated as ordinary.
MCC_RISK: dict[str, float] = {
    "7995": 1.0,  # gambling
    "6051": 1.0,  # quasi-cash / crypto
    "4829": 0.9,  # money transfer
    "5944": 0.6,  # jewelry
    "5732": 0.5,  # electronics
    "5533": 0.3,  # auto parts
}

REMOTE_TYPES = {
    TransactionType.CARD_NOT_PRESENT,
    TransactionType.P2P,
    TransactionType.WIRE,
    TransactionType.ACH,
}


def hard_rules_hit(txn: Transaction, policy: Policy) -> list[str]:
    rules = policy.hard_rules
    hits: list[str] = []
    if txn.merchant.country in rules.sanctioned_countries:
        hits.append(f"SANCTIONED_COUNTRY:{txn.merchant.country}")
    if (
        txn.metadata.device_fingerprint
        and txn.metadata.device_fingerprint in rules.known_bad_devices
    ):
        hits.append("KNOWN_BAD_DEVICE")
    if txn.metadata.ip_address and txn.metadata.ip_address in rules.known_bad_ips:
        hits.append("KNOWN_BAD_IP")
    if rules.amount_ceiling is not None and txn.amount > rules.amount_ceiling:
        hits.append("AMOUNT_CEILING")
    return hits


def signals(txn: Transaction, baseline: UserBaseline | None) -> dict[str, float]:
    s: dict[str, float] = {
        "mcc_risk": MCC_RISK.get(txn.merchant.mcc, 0.0),
        "remote_channel": 1.0 if txn.type in REMOTE_TYPES else 0.0,
    }
    if baseline is None:
        s["no_baseline"] = 1.0
        return s

    ratio = txn.amount / baseline.avg_amount if baseline.avg_amount > 0 else Decimal(10)
    # 1x average -> 0, 10x average -> 1. Below the user's p95 never counts as a spike.
    s["amount_spike"] = (
        0.0 if txn.amount <= baseline.p95_amount else min(1.0, max(0.0, float(ratio - 1) / 9))
    )
    # Missing device/IP is only suspicious when the channel should have provided them.
    missing = 0.5 if txn.type in REMOTE_TYPES else 0.0
    device = txn.metadata.device_fingerprint
    s["new_device"] = missing if device is None else float(device not in baseline.known_devices)
    ip = txn.metadata.ip_address
    s["new_ip"] = missing if ip is None else float(ip not in baseline.known_ips)
    local_hour = (txn.occurred_at + timedelta(hours=baseline.utc_offset_hours)).hour
    s["odd_hour"] = 0.0 if not baseline.active_hours or local_hour in baseline.active_hours else 1.0
    s["foreign_merchant"] = float(txn.merchant.country != baseline.home.country)
    return s


def score(sig: dict[str, float]) -> float:
    keep = 1.0
    for name, value in sig.items():
        keep *= 1.0 - WEIGHTS[name] * value
    return round(1.0 - keep, 4)


def prescreen(txn: Transaction, baseline: UserBaseline | None, policy: Policy) -> Tier0Result:
    started = time.perf_counter()
    hits = hard_rules_hit(txn, policy)
    sig = signals(txn, baseline)
    if hits:
        value, route = 1.0, Tier0Route.EXIT_BLOCK
    else:
        value = score(sig)
        if value <= policy.tier0.approve_max:
            route = Tier0Route.EXIT_APPROVE
        elif value >= policy.tier0.block_min:
            route = Tier0Route.EXIT_BLOCK
        else:
            route = Tier0Route.COURT
    return Tier0Result(
        score=value,
        route=route,
        rules_hit=hits,
        signals={k: round(v, 4) for k, v in sig.items() if v},
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )

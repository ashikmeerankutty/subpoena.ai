"""Clerk (evidence bundle) and Expert Witness signal extraction.

Each expert calls its domain tools through its own MCP session, then turns the results into
candidate signals. The model reviews the candidates against the raw tool output and writes
the final findings; IDs (F1, F2, ...) are assigned afterwards in a fixed order.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from subpoena_schemas import Agent, Evaluation, TransactionType

EXPERTS = [Agent.GEO, Agent.DEVICE, Agent.VELOCITY, Agent.MERCHANT, Agent.GRAPH]
REMOTE = {
    TransactionType.CARD_NOT_PRESENT,
    TransactionType.P2P,
    TransactionType.WIRE,
    TransactionType.ACH,
}


def sig(type_: str, severity: str, supports: str, detail: str) -> dict[str, str]:
    return {"type": type_, "severity": severity, "supports": supports, "detail": detail}


def transaction_view(ev: Evaluation) -> dict[str, Any]:
    t = ev.transaction
    return {
        "transaction_id": t.transaction_id,
        "user_id": t.user_id,
        "amount": str(t.amount),
        "currency": t.currency,
        "type": t.type.value,
        "occurred_at": t.occurred_at.isoformat(),
        "merchant": t.merchant.model_dump(),
        "ip_address": t.metadata.ip_address,
        "device_fingerprint": t.metadata.device_fingerprint,
    }


def geo_signals(ev: Evaluation, tools: dict[str, Any]) -> list[dict[str, str]]:
    g = tools.get("geo_velocity")
    if not g:
        if ev.transaction.type in REMOTE:
            return [
                sig(
                    "NO_IP_ADDRESS",
                    "LOW",
                    "FRAUD",
                    "No IP address was supplied for a remote payment.",
                )
            ]
        return [
            sig("IN_PERSON", "LOW", "LEGIT", "Card-present payment; location is the merchant's.")
        ]
    if not g.get("computable"):
        return [
            sig("UNKNOWN_IP_LOCATION", "MEDIUM", "FRAUD", "The IP address could not be geolocated.")
        ]
    out = []
    if g.get("impossible_travel"):
        out.append(
            sig(
                "IMPOSSIBLE_TRAVEL",
                "CRITICAL",
                "FRAUD",
                f"Implied travel speed of {g['implied_speed_kmh']:.0f} km/h from {g['last_seen_city']} "
                f"to {g['ip_city']} in {g['hours_since_last_seen']:.1f} h.",
            )
        )
    if g["ip_country"] != (tools.get("home_country") or g["ip_country"]):
        out.append(
            sig(
                "FOREIGN_IP",
                "HIGH",
                "FRAUD",
                f"IP geolocates to {g['ip_city']}, {g['ip_country']}, {g['distance_from_home_km']:.0f} km "
                f"from the cardholder's home in {g['home_city']}.",
            )
        )
    elif g["distance_from_home_km"] < 100:
        out.append(
            sig(
                "IP_NEAR_HOME",
                "LOW",
                "LEGIT",
                f"IP geolocates to {g['ip_city']}, {g['distance_from_home_km']:.0f} km from home "
                f"({g['home_city']}).",
            )
        )
    else:
        out.append(
            sig(
                "DISTANT_IP",
                "MEDIUM",
                "FRAUD",
                f"IP geolocates to {g['ip_city']}, {g['distance_from_home_km']:.0f} km from home "
                f"({g['home_city']}).",
            )
        )
    return out


def device_signals(
    ev: Evaluation, tools: dict[str, Any], baseline: dict[str, Any]
) -> list[dict[str, str]]:
    out = []
    device = ev.transaction.metadata.device_fingerprint
    if device:
        if device in baseline.get("known_devices", []):
            out.append(
                sig(
                    "KNOWN_DEVICE",
                    "LOW",
                    "LEGIT",
                    f"Device {device} has been used by this cardholder before.",
                )
            )
        else:
            n = len(baseline.get("known_devices", []))
            out.append(
                sig(
                    "NEW_DEVICE",
                    "MEDIUM",
                    "FRAUD",
                    f"Device {device} has never been seen for this cardholder ({n} known devices in 90 days).",
                )
            )
    asn = tools.get("query_asn_reputation")
    if asn and asn.get("known"):
        if asn["risk"] == "HIGH":
            out.append(
                sig(
                    "VPN_OR_HOSTING_IP",
                    "HIGH",
                    "FRAUD",
                    f"IP belongs to {asn['asn_org']} (AS{asn['asn']}), a {asn['asn_type'].lower()} network"
                    f"{' used as a VPN exit' if asn.get('is_vpn_or_proxy') else ''}.",
                )
            )
        else:
            out.append(
                sig(
                    "RESIDENTIAL_ISP",
                    "LOW",
                    "LEGIT",
                    f"IP belongs to residential ISP {asn['asn_org']} (AS{asn['asn']}).",
                )
            )
    return out


def velocity_signals(
    ev: Evaluation, baseline: dict[str, Any], recent: list[dict[str, Any]]
) -> list[dict[str, str]]:
    t = ev.transaction
    out = []
    if not baseline.get("avg_amount"):
        return [
            sig("NO_HISTORY", "MEDIUM", "FRAUD", "No spending history exists for this cardholder.")
        ]
    avg, p95 = Decimal(str(baseline["avg_amount"])), Decimal(str(baseline["p95_amount"]))
    ratio = float(t.amount / avg) if avg else 0.0
    if t.amount > p95:
        severity = "HIGH" if ratio >= 10 else "MEDIUM"
        out.append(
            sig(
                "AMOUNT_SPIKE",
                severity,
                "FRAUD",
                f"${t.amount:,.2f} is {ratio:.1f}x the 90-day average of ${avg:,.2f} "
                f"and above the 95th percentile (${p95:,.2f}).",
            )
        )
    else:
        out.append(
            sig(
                "AMOUNT_WITHIN_RANGE",
                "LOW",
                "LEGIT",
                f"${t.amount:,.2f} is within the cardholder's normal range (95th percentile ${p95:,.2f}).",
            )
        )
    local = t.occurred_at + timedelta(hours=int(baseline.get("utc_offset_hours", 0)))
    hours = baseline.get("active_hours") or []
    if hours and local.hour not in hours:
        out.append(
            sig(
                "UNUSUAL_HOUR",
                "LOW",
                "FRAUD",
                f"Made at {local:%H:%M} local time; the cardholder is normally active "
                f"{min(hours):02d}:00-{max(hours):02d}:59.",
            )
        )
    same = [r for r in recent if r["merchant"]["mcc"] == t.merchant.mcc]
    if same:
        top = max(Decimal(str(r["amount"])) for r in same)
        out.append(
            sig(
                "CATEGORY_HISTORY",
                "MEDIUM",
                "LEGIT",
                f"{len(same)} prior purchases in this category (MCC {t.merchant.mcc}) in recent history, "
                f"up to ${top:,.2f}.",
            )
        )
    else:
        out.append(
            sig(
                "NEW_CATEGORY",
                "LOW",
                "FRAUD",
                f"No prior purchases in this category (MCC {t.merchant.mcc}) in recent history.",
            )
        )
    return out


def merchant_signals(tools: dict[str, Any]) -> list[dict[str, str]]:
    m = tools.get("validate_merchant") or {}
    if not m.get("found"):
        return [
            sig(
                "MERCHANT_UNKNOWN",
                "MEDIUM",
                "FRAUD",
                f"Merchant {m.get('merchant_name')} is not in any registry.",
            )
        ]
    out = []
    status = m["status"]
    if status == "VERIFIED":
        out.append(
            sig(
                "MERCHANT_VERIFIED",
                "LOW",
                "LEGIT",
                f"{m['merchant_name']} is a verified merchant operating since {m['operating_since']}.",
            )
        )
    elif status == "SANCTIONED":
        out.append(
            sig(
                "MERCHANT_SANCTIONED",
                "CRITICAL",
                "FRAUD",
                f"{m['merchant_name']}: {m.get('note')}.",
            )
        )
    else:
        out.append(
            sig(
                "MERCHANT_UNVERIFIED",
                "HIGH",
                "FRAUD",
                f"{m['merchant_name']} is unverified: {m.get('note') or 'no registration found'}.",
            )
        )
    if not m.get("mcc_matches", True):
        out.append(
            sig(
                "MCC_MISMATCH",
                "MEDIUM",
                "FRAUD",
                f"Category code does not match the registered MCC {m['registered_mcc']}.",
            )
        )
    return out


def graph_signals(graphs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for entity, g in graphs.items():
        flagged = [n for n in g.get("neighbors", []) if n.get("flag") in ("MULE", "MULE_LINKED")]
        if g.get("flag") or flagged:
            names = ", ".join(sorted({n["id"] for n in flagged})[:3])
            out.append(
                sig(
                    "MULE_NETWORK_LINK",
                    "CRITICAL",
                    "FRAUD",
                    f"{entity} is linked to {len(flagged)} flagged mule entities ({names}).",
                )
            )
    if not out:
        out.append(
            sig(
                "NO_GRAPH_LINKS",
                "INFO",
                "NEUTRAL",
                "No links to known mule accounts, devices or payees.",
            )
        )
    return out

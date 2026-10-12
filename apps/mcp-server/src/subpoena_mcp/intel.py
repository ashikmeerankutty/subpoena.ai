"""Deterministic risk intelligence behind the read-only MCP tools."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .data import DataSource

MAX_PLAUSIBLE_KMH = 900.0  # faster than a commercial flight


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def asn_reputation(data: DataSource, ip_address: str) -> dict[str, Any]:
    info = data.ip_info(ip_address)
    if info is None:
        return {"ip_address": ip_address, "known": False, "risk": "UNKNOWN"}
    hosting = info.get("asn_type") == "HOSTING"
    vpn = bool(info.get("known_vpn"))
    return {
        "ip_address": ip_address,
        "known": True,
        "asn": info["asn"],
        "asn_org": info["asn_org"],
        "asn_type": info["asn_type"],
        "is_vpn_or_proxy": vpn,
        "risk": "HIGH" if (hosting or vpn) else "LOW",
    }


def geo_velocity(
    data: DataSource, user_id: str, ip_address: str, timestamp: datetime
) -> dict[str, Any]:
    info = data.ip_info(ip_address)
    baseline = data.baseline(user_id)
    if info is None or baseline is None:
        return {"computable": False, "reason": "unknown IP location or user"}
    here = (info["lat"], info["lng"])
    home = (baseline.home.lat, baseline.home.lng)

    # Last location we saw this user at: the most recent prior txn with a geolocatable IP.
    last_loc, last_at, last_city = home, None, baseline.home.city
    for txn in data.recent_transactions(user_id, limit=50, before=timestamp):
        prev = (txn.get("metadata") or {}).get("ip_address")
        prev_info = data.ip_info(prev) if prev else None
        if prev_info:
            last_loc, last_city = (prev_info["lat"], prev_info["lng"]), prev_info["city"]
            last_at = datetime.fromisoformat(str(txn["occurred_at"]).replace("Z", "+00:00"))
            break

    distance = haversine_km(last_loc, here)
    result: dict[str, Any] = {
        "computable": True,
        "ip_city": info["city"],
        "ip_country": info["country"],
        "home_city": baseline.home.city,
        "distance_from_home_km": round(haversine_km(home, here), 1),
        "last_seen_city": last_city,
        "distance_from_last_seen_km": round(distance, 1),
    }
    if last_at is not None:
        hours = max((timestamp - last_at).total_seconds() / 3600, 1 / 60)
        speed = distance / hours
        result |= {
            "hours_since_last_seen": round(hours, 2),
            "implied_speed_kmh": round(speed, 1),
            "impossible_travel": speed > MAX_PLAUSIBLE_KMH,
        }
    return result


def validate_merchant(data: DataSource, merchant_name: str, mcc: str) -> dict[str, Any]:
    record = data.merchant(merchant_name)
    if record is None:
        return {"merchant_name": merchant_name, "found": False, "risk": "MEDIUM"}
    status = record["status"]
    return {
        "merchant_name": record["name"],
        "found": True,
        "status": status,
        "registered_mcc": record["mcc"],
        "mcc_matches": record["mcc"] == mcc,
        "operating_since": record.get("since"),
        "note": record.get("note"),
        "risk": {"VERIFIED": "LOW", "UNVERIFIED": "HIGH", "SANCTIONED": "CRITICAL"}.get(
            status, "MEDIUM"
        ),
    }

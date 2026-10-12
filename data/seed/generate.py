"""Generate deterministic synthetic seed data.

Writes, next to this file:
  users.json         demo + background cardholders (phone, home, devices, SIM-swap state)
  transactions.jsonl 90 days of history per user (BigQuery-loadable, one JSON object per line)
  baselines.json     per-user behavioural baselines computed from that history
  graph.json         entity edges (users, devices, IPs, payees) incl. a small mule ring
  scenarios.json     demo requests for POST /v1/evaluations with expected routing/verdicts

Usage: uv run python data/seed/generate.py
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent
SEED = 42
END = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)  # history ends just before the demo transactions
DAYS = 90


@dataclass(frozen=True)
class Spend:
    merchant: str
    mcc: str
    lo: float
    hi: float
    weight: float
    type: str = "CARD_PRESENT"
    hours: tuple[int, int] = (8, 22)  # local hours, inclusive range


@dataclass
class User:
    user_id: str
    name: str
    phone: str
    city: str
    country: str
    lat: float
    lng: float
    utc_offset: int
    devices: list[str]
    ips: list[str]
    per_day: float
    spends: list[Spend]
    sim_swap_hours_ago: int | None = None  # relative, so the demo never goes stale
    tags: list[str] = field(default_factory=list)


EVERYDAY = [
    Spend("Blue Bottle Coffee", "5814", 4, 9, 6, hours=(7, 11)),
    Spend("Safeway", "5411", 25, 180, 4),
    Spend("Chevron", "5541", 30, 85, 2),
    Spend("Netflix", "4899", 15.49, 15.49, 0.3, "CARD_NOT_PRESENT"),
    Spend("Amazon.com", "5942", 12, 140, 2, "CARD_NOT_PRESENT", (9, 23)),
    Spend("Chipotle", "5814", 11, 28, 3, hours=(11, 21)),
]

AUTO_HOBBY = [
    Spend("AutoZone Online", "5533", 180, 1400, 0.8, "CARD_NOT_PRESENT", (18, 23)),
    Spend("FCP Euro", "5533", 250, 1800, 0.5, "CARD_NOT_PRESENT", (18, 23)),
    Spend("Pelican Parts", "5533", 300, 2200, 0.3, "CARD_NOT_PRESENT", (19, 23)),
]

CITIES = [
    ("San Francisco", "US", 37.7749, -122.4194, -7),
    ("New York", "US", 40.7128, -74.0060, -4),
    ("Chicago", "US", 41.8781, -87.6298, -5),
    ("Austin", "US", 30.2672, -97.7431, -5),
    ("Seattle", "US", 47.6062, -122.3321, -7),
    ("Lisbon", "PT", 38.7223, -9.1393, 1),
    ("London", "GB", 51.5072, -0.1276, 1),
]

FIRST = [
    "Priya",
    "Diego",
    "Mei",
    "Tomás",
    "Fatima",
    "Noah",
    "Aisha",
    "Lucas",
    "Hana",
    "Omar",
    "Elena",
    "Kwame",
    "Sofia",
    "Ravi",
    "Ines",
    "Mateo",
    "Yuki",
    "Zara",
    "Ben",
    "Leila",
]
LAST = ["Shah", "García", "Chen", "Silva", "Haddad", "Kim", "Mensah", "Costa", "Novak", "Ali"]


def ip(rng: random.Random, block: str = "198.18") -> str:
    return f"{block}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


def device(rng: random.Random) -> str:
    return f"dev-{rng.getrandbits(48):012x}"


def demo_users(rng: random.Random) -> list[User]:
    alex = User(
        "usr_9921",
        "Alex Rivera",
        "+14155550123",
        "San Francisco",
        "US",
        37.7749,
        -122.4194,
        -7,
        devices=["dev-alex-iphone15", "dev-alex-macbook"],
        ips=["198.18.10.21", "198.18.10.22"],
        per_day=2.6,
        spends=EVERYDAY + AUTO_HOBBY,
        tags=["demo", "deadlock"],
    )
    sam = User(
        "usr_2002",
        "Sam Okafor",
        "+14155550188",
        "San Francisco",
        "US",
        37.7749,
        -122.4194,
        -7,
        devices=["dev-sam-pixel8"],
        ips=["198.18.20.40"],
        per_day=2.4,
        spends=EVERYDAY + AUTO_HOBBY,
        sim_swap_hours_ago=20,
        tags=["demo", "sim_swap"],
    )
    jordan = User(
        "usr_3003",
        "Jordan Lee",
        "+13125550147",
        "Chicago",
        "US",
        41.8781,
        -87.6298,
        -5,
        devices=["dev-jordan-galaxy"],
        ips=["198.18.30.77"],
        per_day=2.0,
        spends=EVERYDAY,
        tags=["demo", "clear_fraud"],
    )
    return [alex, sam, jordan]


def background_users(rng: random.Random, n: int) -> list[User]:
    users = []
    for i in range(n):
        city, country, lat, lng, off = rng.choice(CITIES)
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        spends = list(EVERYDAY)
        if rng.random() < 0.3:
            spends += AUTO_HOBBY[:1]
        if rng.random() < 0.2:
            spends.append(Spend("Best Buy", "5732", 60, 1600, 0.4, "CARD_PRESENT"))
        if rng.random() < 0.15:
            spends.append(Spend("Tiffany & Co.", "5944", 200, 3000, 0.1))
        users.append(
            User(
                f"usr_{4000 + i}",
                name,
                f"+1415555{1000 + i:04d}",
                city,
                country,
                lat,
                lng,
                off,
                devices=[device(rng) for _ in range(rng.randint(1, 3))],
                ips=[ip(rng) for _ in range(rng.randint(1, 3))],
                per_day=rng.uniform(1.2, 3.5),
                spends=spends,
            )
        )
    return users


def money(x: float) -> str:
    return str(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def history(rng: random.Random, u: User) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    weights = [s.weight for s in u.spends]
    seq = 0
    for d in range(DAYS):
        day = END - timedelta(days=DAYS - d)
        # Poisson-ish count per day
        count = max(0, round(rng.gauss(u.per_day, math.sqrt(u.per_day))))
        for _ in range(count):
            s = rng.choices(u.spends, weights)[0]
            local_hour = rng.randint(*s.hours)
            ts = day + timedelta(
                hours=local_hour - u.utc_offset,
                minutes=rng.randint(0, 59),
                seconds=rng.randint(0, 59),
            )
            seq += 1
            rows.append(
                {
                    "transaction_id": f"tx_{u.user_id[4:]}_{seq:05d}",
                    "user_id": u.user_id,
                    "amount": money(rng.uniform(s.lo, s.hi)),
                    "currency": "USD",
                    "type": s.type,
                    "occurred_at": ts.isoformat().replace("+00:00", "Z"),
                    "merchant": {"name": s.merchant, "mcc": s.mcc, "country": "US"},
                    "metadata": {
                        "ip_address": rng.choice(u.ips) if s.type != "CARD_PRESENT" else None,
                        "device_fingerprint": rng.choice(u.devices)
                        if s.type != "CARD_PRESENT"
                        else None,
                    },
                    "label": "LEGIT",
                }
            )
    rows.sort(key=lambda r: r["occurred_at"])
    return rows


def baseline(u: User, rows: list[dict[str, Any]]) -> dict[str, Any]:
    amounts = sorted(Decimal(r["amount"]) for r in rows)
    avg = sum(amounts, Decimal(0)) / len(amounts)
    p95 = amounts[min(len(amounts) - 1, math.ceil(0.95 * len(amounts)) - 1)]
    hours = sorted(
        {
            (datetime.fromisoformat(r["occurred_at"]) + timedelta(hours=u.utc_offset)).hour
            for r in rows
        }
    )
    mcc_counts: dict[str, int] = {}
    for r in rows:
        mcc_counts[r["merchant"]["mcc"]] = mcc_counts.get(r["merchant"]["mcc"], 0) + 1
    return {
        "user_id": u.user_id,
        "home": {"lat": u.lat, "lng": u.lng, "city": u.city, "country": u.country},
        "utc_offset_hours": u.utc_offset,
        "known_devices": sorted({r["metadata"]["device_fingerprint"] for r in rows} - {None}),
        "known_ips": sorted({r["metadata"]["ip_address"] for r in rows} - {None}),
        "avg_amount": money(float(avg)),
        "p95_amount": str(p95),
        "txn_per_day": round(len(rows) / DAYS, 2),
        "active_hours": hours,
        "common_mccs": [m for m, _ in sorted(mcc_counts.items(), key=lambda kv: -kv[1])[:5]],
        "window_days": DAYS,
        "computed_at": END.isoformat().replace("+00:00", "Z"),
    }


def graph(users: list[User]) -> dict[str, Any]:
    edges: list[dict[str, str]] = []
    for u in users:
        edges += [{"src": u.user_id, "dst": d, "type": "USES_DEVICE"} for d in u.devices]
        edges += [{"src": u.user_id, "dst": i, "type": "USES_IP"} for i in u.ips]
    # A mule ring: three mule accounts sharing one device and IP, all paid by a known payee.
    mules = ["acct_mule_01", "acct_mule_02", "acct_mule_03"]
    for m in mules:
        edges += [
            {"src": m, "dst": "dev-mule-shared-01", "type": "USES_DEVICE"},
            {"src": m, "dst": "198.51.100.66", "type": "USES_IP"},
            {"src": "payee_quickcash_7781", "dst": m, "type": "PAYS_OUT_TO"},
        ]
    return {
        "nodes": {
            "flagged": [
                {"id": m, "kind": "ACCOUNT", "flag": "MULE", "since": "2026-08-14"} for m in mules
            ]
            + [
                {"id": "dev-mule-shared-01", "kind": "DEVICE", "flag": "MULE_LINKED"},
                {"id": "198.51.100.66", "kind": "IP", "flag": "MULE_LINKED"},
                {"id": "payee_quickcash_7781", "kind": "PAYEE", "flag": "MULE_LINKED"},
            ]
        },
        "edges": edges,
    }


def scenarios() -> list[dict[str, Any]]:
    def req(**kw: Any) -> dict[str, Any]:
        base: dict[str, Any] = {"currency": "USD", "options": {"sync_timeout_ms": 8000}}
        return base | kw

    return [
        {
            "name": "coffee",
            "description": "Routine $12 coffee on a known card — exits Tier 0 approved.",
            "expected": {"tier0_route": "EXIT_APPROVE", "verdict": "APPROVE"},
            "request": req(
                transaction_id="tx_demo_coffee",
                user_id="usr_9921",
                amount=12.40,
                type="CARD_PRESENT",
                occurred_at="2026-10-09T15:32:10Z",
                merchant={"name": "Blue Bottle Coffee", "mcc": "5814", "country": "US"},
                metadata={},
                witness={"phone": "+14155550123", "allowed_channels": ["WHATSAPP", "SMS"]},
            ),
        },
        {
            "name": "auto_parts_deadlock",
            "description": "$4,500 auto parts at 2:14 AM local from a new device — goes to court, "
            "deadlocks, subpoena; cardholder confirms → APPROVE.",
            "expected": {"tier0_route": "COURT", "first_ruling": "SUBPOENA", "verdict": "APPROVE"},
            "request": req(
                transaction_id="tx_8839201",
                user_id="usr_9921",
                amount=4500.00,
                type="CARD_NOT_PRESENT",
                occurred_at="2026-10-09T09:14:03Z",
                merchant={"name": "AutoZone Online", "mcc": "5533", "country": "US"},
                metadata={
                    "ip_address": "203.0.113.44",
                    "device_fingerprint": "abc-123",
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5)",
                },
                witness={
                    "phone": "+14155550123",
                    "allowed_channels": ["WHATSAPP", "SMS"],
                    "locale": "en-US",
                },
            ),
            "testimony": {"reply": "Yes, parts for my BMW E36 project", "otp_passes": True},
        },
        {
            "name": "sim_swap",
            "description": "Same purchase pattern for a user whose SIM was swapped yesterday — "
            "Bailiff Lookup fails → BLOCK + ESCALATE.",
            "expected": {
                "tier0_route": "COURT",
                "first_ruling": "SUBPOENA",
                "verdict": "BLOCK",
                "status": "ESCALATED",
            },
            "request": req(
                transaction_id="tx_demo_simswap",
                user_id="usr_2002",
                amount=4500.00,
                type="CARD_NOT_PRESENT",
                occurred_at="2026-10-09T09:20:41Z",
                merchant={"name": "AutoZone Online", "mcc": "5533", "country": "US"},
                metadata={"ip_address": "203.0.113.90", "device_fingerprint": "dev-unknown-7f3a"},
                witness={"phone": "+14155550188", "allowed_channels": ["WHATSAPP", "SMS"]},
            ),
        },
        {
            "name": "clear_fraud",
            "description": "$9,800 P2P to a mule-linked payee from a mule-ring IP — the courtroom "
            "blocks without bothering the customer.",
            "expected": {"tier0_route": "COURT", "verdict": "BLOCK"},
            "request": req(
                transaction_id="tx_demo_mule",
                user_id="usr_3003",
                amount=9800.00,
                type="P2P",
                occurred_at="2026-10-09T08:03:55Z",
                merchant={"name": "QuickCash Transfers", "mcc": "4829", "country": "US"},
                metadata={
                    "ip_address": "198.51.100.66",
                    "device_fingerprint": "dev-mule-shared-01",
                },
                witness={"phone": "+13125550147", "allowed_channels": ["SMS"]},
            ),
        },
        {
            "name": "sanctioned_country",
            "description": "Merchant in a sanctioned country — blocked by a Tier 0 hard rule.",
            "expected": {"tier0_route": "EXIT_BLOCK", "verdict": "BLOCK"},
            "request": req(
                transaction_id="tx_demo_sanctioned",
                user_id="usr_3003",
                amount=250.00,
                type="CARD_NOT_PRESENT",
                occurred_at="2026-10-09T13:00:00Z",
                merchant={"name": "Pyongyang Trading Co", "mcc": "5999", "country": "KP"},
                metadata={"ip_address": "198.18.30.77", "device_fingerprint": "dev-jordan-galaxy"},
            ),
        },
    ]


def ip_geo(users: list[User]) -> dict[str, Any]:
    """Synthetic IP intelligence: geolocation and ASN for every IP in the dataset."""
    geo: dict[str, Any] = {}
    for u in users:
        for addr in u.ips:
            geo[addr] = {
                "lat": u.lat,
                "lng": u.lng,
                "city": u.city,
                "country": u.country,
                "asn": 7922,
                "asn_org": "Comcast Cable",
                "asn_type": "RESIDENTIAL",
            }
    geo["203.0.113.44"] = {
        "lat": 37.8044,
        "lng": -122.2712,
        "city": "Oakland",
        "country": "US",
        "asn": 7018,
        "asn_org": "AT&T Services",
        "asn_type": "RESIDENTIAL",
    }
    geo["203.0.113.90"] = {
        "lat": 34.0522,
        "lng": -118.2437,
        "city": "Los Angeles",
        "country": "US",
        "asn": 7018,
        "asn_org": "AT&T Services",
        "asn_type": "RESIDENTIAL",
    }
    geo["198.51.100.66"] = {
        "lat": 6.5244,
        "lng": 3.3792,
        "city": "Lagos",
        "country": "NG",
        "asn": 9009,
        "asn_org": "M247 Europe (VPN exit)",
        "asn_type": "HOSTING",
        "known_vpn": True,
    }
    return geo


def merchants() -> list[dict[str, Any]]:
    """Synthetic merchant registry standing in for Places API lookups."""

    def m(name: str, mcc: str, status: str = "VERIFIED", **kw: Any) -> dict[str, Any]:
        return {"name": name, "mcc": mcc, "status": status, **kw}

    return [
        m("Blue Bottle Coffee", "5814", website="bluebottlecoffee.com", since="2002"),
        m("Safeway", "5411", website="safeway.com", since="1915"),
        m("Chevron", "5541", website="chevron.com", since="1879"),
        m("Netflix", "4899", website="netflix.com", since="1997"),
        m("Amazon.com", "5942", website="amazon.com", since="1994"),
        m("Chipotle", "5814", website="chipotle.com", since="1993"),
        m("AutoZone Online", "5533", website="autozone.com", since="1979"),
        m("FCP Euro", "5533", website="fcpeuro.com", since="1986"),
        m("Pelican Parts", "5533", website="pelicanparts.com", since="1995"),
        m("Best Buy", "5732", website="bestbuy.com", since="1966"),
        m("Tiffany & Co.", "5944", website="tiffany.com", since="1837"),
        m(
            "QuickCash Transfers",
            "4829",
            "UNVERIFIED",
            since="2026-09-17",
            note="No business registration found; domain registered 3 weeks ago",
        ),
        m("Pyongyang Trading Co", "5999", "SANCTIONED", note="OFAC SDN list match"),
    ]


def precedents() -> list[dict[str, Any]]:
    """Seed case law for the Defense and Judge (stand-in for the vector-searched library)."""
    return [
        {
            "id": "P1",
            "summary": "Late-night $3,900 CNP auto-parts order from a new laptop by a "
            "user with a history of auto-parts purchases; cardholder confirmed via OTP.",
            "verdict": "APPROVE",
            "label": "LEGIT",
            "tags": ["auto_parts", "new_device", "night"],
        },
        {
            "id": "P2",
            "summary": "$7,500 P2P transfer to a payee created days earlier, from a "
            "hosting-ASN IP linked to two known mule accounts.",
            "verdict": "BLOCK",
            "label": "FRAUD",
            "tags": ["p2p", "mule", "vpn", "new_payee"],
        },
        {
            "id": "P3",
            "summary": "High-value CNP purchase shortly after a SIM swap on the "
            "cardholder's number; OTP was answered by the attacker.",
            "verdict": "BLOCK",
            "label": "FRAUD",
            "tags": ["sim_swap", "ato", "new_device"],
        },
        {
            "id": "P4",
            "summary": "Electronics purchase 8x the user's average while travelling; "
            "IP matched the user's hotel city and cardholder confirmed.",
            "verdict": "APPROVE",
            "label": "LEGIT",
            "tags": ["amount_spike", "travel"],
        },
    ]


def main() -> None:
    rng = random.Random(SEED)
    users = demo_users(rng) + background_users(rng, 20)
    all_rows: list[dict[str, Any]] = []
    baselines = []
    for u in users:
        rows = history(rng, u)
        all_rows += rows
        baselines.append(baseline(u, rows))

    users_out = [
        {
            "user_id": u.user_id,
            "name": u.name,
            "phone": u.phone,
            "home": {"city": u.city, "country": u.country, "lat": u.lat, "lng": u.lng},
            "utc_offset_hours": u.utc_offset,
            "devices": u.devices,
            "ips": u.ips,
            "sim_swap_hours_ago": u.sim_swap_hours_ago,
            "tags": u.tags,
        }
        for u in users
    ]

    def dump(name: str, obj: Any) -> None:
        (OUT / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

    dump("users.json", users_out)
    dump("baselines.json", baselines)
    dump("graph.json", graph(users))
    dump("scenarios.json", scenarios())
    dump("ip_geo.json", ip_geo(users))
    dump("merchants.json", merchants())
    dump("precedents.json", precedents())
    with (OUT / "transactions.jsonl").open("w") as f:
        for r in sorted(all_rows, key=lambda r: r["occurred_at"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(users)} users, {len(all_rows)} transactions written to {OUT}")


if __name__ == "__main__":
    main()

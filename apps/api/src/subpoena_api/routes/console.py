"""Read models for the Courthouse Console (Spec §10): overview, subpoenas, sources, policies."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError

from subpoena_schemas import (
    ApiKey,
    ApiKeyPublic,
    Evaluation,
    EvaluationResponse,
    EvaluationStatus,
    KeyKind,
    Policy,
    Scope,
    Subpoena,
    SubpoenaState,
    Tier0Route,
    Verdict,
    decide,
    role_for,
    utcnow,
)
from subpoena_store import EvaluationFilters

from ..deps import ServicesDep, active_policy, audit, require
from ..problems import ProblemError
from ..webhooks import workspace_secret

router = APIRouter(prefix="/v1", tags=["console"])
ReadKey = Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_READ))]
AdminKey = Annotated[ApiKey, Depends(require(Scope.ADMIN))]

STATS_WINDOW_LIMIT = 2000


@router.get("/me")
async def me(key: ReadKey, services: ServicesDep) -> dict[str, Any]:
    ws = await services.store.get_workspace(key.workspace_id)
    session = key.kind is KeyKind.SESSION
    return {
        "workspace": ws.model_dump(mode="json") if ws else {"id": key.workspace_id},
        "key": ApiKeyPublic.from_key(key).model_dump(mode="json"),
        "role": role_for(key.scopes),
        "principal": {
            "type": "MEMBER" if session else "API_KEY",
            "name": key.name,
            "email": key.name if session else None,
            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        },
        "simulator": services.settings.witness_simulator,
    }


@router.get("/stats/overview")
async def overview(
    key: ReadKey, services: ServicesDep, hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24
) -> dict[str, Any]:
    since = utcnow() - timedelta(hours=hours)
    evs = await services.store.list_evaluations(
        key.workspace_id, EvaluationFilters(created_from=since), STATS_WINDOW_LIMIT, None
    )
    n = len(evs)
    court = [e for e in evs if e.tier0 and e.tier0.route is Tier0Route.COURT]
    verdicts = Counter(e.verdict.value if e.verdict else "PENDING" for e in evs)
    statuses = Counter(e.status.value for e in evs)
    subpoenaed = [e for e in evs if e.subpoena is not None]
    answered = [e for e in subpoenaed if e.testimony is not None]
    latencies = [
        (e.ruled_at - e.created_at).total_seconds() for e in evs if e.ruled_at and not e.subpoena
    ]
    court_lat = [
        (e.ruled_at - e.created_at).total_seconds() for e in court if e.ruled_at and not e.subpoena
    ]
    ttt = [
        (e.testimony.received_at - e.subpoena.sent_at).total_seconds()
        for e in answered
        if e.testimony and e.subpoena
    ]
    costs = [e.cost_usd for e in court if e.cost_usd is not None]
    signals = Counter(f.type for e in court for f in e.findings if f.supports == "FRAUD")
    # ~12-48 bars whatever the window: 5-minute buckets for an hour, hourly for a day, 6h for a week.
    bucket_minutes = 5 if hours <= 2 else 60 if hours <= 48 else 360
    buckets: dict[str, Counter[str]] = {}
    for e in evs:
        ts = e.created_at.timestamp()
        start = datetime.fromtimestamp(ts - ts % (bucket_minutes * 60), tz=UTC).isoformat()
        buckets.setdefault(start, Counter())[e.verdict.value if e.verdict else "PENDING"] += 1
    avoided = sum(1 for e in answered if e.verdict is Verdict.APPROVE)
    subs = [
        s
        for s in await services.store.list_subpoenas(key.workspace_id, STATS_WINDOW_LIMIT)
        if s.sent_at >= since
    ]

    def rate(k: int) -> float:
        return round(k / n, 4) if n else 0.0

    def median(xs: list[float]) -> float | None:
        return round(statistics.median(xs), 2) if xs else None

    return {
        "window_hours": hours,
        "evaluations": n,
        "evaluations_per_hour": round(n / hours, 2),
        "sent_to_court": len(court),
        "rates": {
            "approve": rate(verdicts["APPROVE"]),
            "block": rate(verdicts["BLOCK"]),
            "subpoena": rate(len(subpoenaed)),
            "escalate": rate(statuses["ESCALATED"]),
        },
        "verdicts": dict(verdicts),
        "statuses": dict(statuses),
        "median_decision_latency_s": median(latencies),
        "median_courtroom_latency_s": median(court_lat),
        "subpoenas": len(subpoenaed),
        "subpoena_resolution_rate": round(len(answered) / len(subpoenaed), 4)
        if subpoenaed
        else None,
        "median_time_to_testimony_s": median(ttt),
        "false_positives_avoided": avoided,
        "cost_per_courtroom_case_usd": round(statistics.mean(costs), 4) if costs else None,
        "total_cost_usd": round(sum(costs), 4),
        "top_risk_signals": signals.most_common(8),
        "impact": _impact(evs, subs),
        "economics": _economics(evs, costs),
        "bucket_minutes": bucket_minutes,
        "series": [{"hour": h, **dict(c)} for h, c in sorted(buckets.items())],
    }


def _impact(evs: list[Evaluation], subs: list[Subpoena]) -> dict[str, Any]:
    """What the decisions meant for cardholders. Amounts are summed per currency, never converted."""
    saved: defaultdict[str, Decimal] = defaultdict(Decimal)
    stopped: defaultdict[str, Decimal] = defaultdict(Decimal)
    saved_n = stopped_n = denied_by_witness = auto = 0
    for e in evs:
        tx = e.transaction
        if e.verdict is Verdict.APPROVE and e.testimony and e.testimony.claims.confirms_transaction:
            saved[tx.currency] += tx.amount
            saved_n += 1
        if e.verdict is Verdict.BLOCK:
            stopped[tx.currency] += tx.amount
            stopped_n += 1
            if e.testimony and e.testimony.claims.confirms_transaction is False:
                denied_by_witness += 1
        if (
            e.verdict is not None
            and e.subpoena is None
            and e.status is not EvaluationStatus.ESCALATED
        ):
            auto += 1
    flagged = sum(1 for e in evs if e.testimony and e.testimony.flagged_by_screening)
    # Payment to final decision, including the cases that waited for the cardholder's reply.
    resolution = [(e.ruled_at - e.created_at).total_seconds() for e in evs if e.ruled_at]
    states = Counter(s.state for s in subs)
    return {
        "legit_spend_saved": {"count": saved_n, "amounts": _money(saved)},
        "fraud_stopped": {
            "count": stopped_n,
            "amounts": _money(stopped),
            "denied_by_cardholder": denied_by_witness,
        },
        "customers_not_contacted_rate": round(auto / len(evs), 4) if evs else None,
        "median_resolution_s": round(statistics.median(resolution), 2) if resolution else None,
        "witness_protection": {
            "sim_swap_blocked": states[SubpoenaState.AUTH_FAILED],
            "code_failed": states[SubpoenaState.CODE_FAILED],
            "testimony_flagged": flagged,
        },
    }


def _economics(evs: list[Evaluation], costs: list[float]) -> dict[str, Any]:
    """Where model spend goes: Tier 0 (hard rules included) decides for free; only the courtroom calls Gemini."""
    routes = Counter(e.tier0.route for e in evs if e.tier0)
    spend = sum(costs)
    # Only USD amounts count toward the ratio; other currencies are never converted.
    protected = sum(
        (
            e.transaction.amount
            for e in evs
            if e.transaction.currency == "USD"
            and (
                e.verdict is Verdict.BLOCK
                or (
                    e.verdict is Verdict.APPROVE
                    and e.testimony
                    and e.testimony.claims.confirms_transaction
                )
            )
        ),
        Decimal(0),
    )
    return {
        "tiers": {
            "tier0_approve": routes[Tier0Route.EXIT_APPROVE],
            "tier0_block": routes[Tier0Route.EXIT_BLOCK],
            "courtroom": routes[Tier0Route.COURT],
        },
        "decided_without_model_rate": round(1 - routes[Tier0Route.COURT] / len(evs), 4)
        if evs
        else None,
        "ai_spend_usd": round(spend, 4),
        "cost_per_evaluation_usd": round(spend / len(evs), 5) if evs else None,
        "usd_protected": f"{protected:.2f}",
        "usd_protected_per_ai_dollar": round(float(protected) / spend) if spend else None,
    }


def _money(totals: dict[str, Decimal]) -> dict[str, str]:
    return {c: f"{v:.2f}" for c, v in sorted(totals.items(), key=lambda kv: -kv[1])}


@router.get("/subpoenas")
async def list_subpoenas(
    key: ReadKey, services: ServicesDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> dict[str, Any]:
    subs = await services.store.list_subpoenas(key.workspace_id, limit)
    rows = []
    for s in subs:
        ev = await services.store.get_evaluation(key.workspace_id, s.evaluation_id)
        rows.append(
            {
                **s.model_dump(mode="json", exclude={"pending_code"}),
                "evaluation": EvaluationResponse.from_evaluation(ev).model_dump(mode="json")
                if ev
                else None,
            }
        )
    return {"data": rows, "meta": {"next_page_token": None}}


@router.get("/subpoenas/{subpoena_id}")
async def get_subpoena(subpoena_id: str, key: ReadKey, services: ServicesDep) -> dict[str, Any]:
    s = await services.store.get_subpoena(subpoena_id)
    if s is None or s.workspace_id != key.workspace_id:
        raise ProblemError(404, "not-found", f"Subpoena {subpoena_id} not found")
    msgs = [
        m
        for m in await services.store.list_messages(s.phone)
        if m.workspace_id in (None, key.workspace_id)
    ]
    return {
        **s.model_dump(mode="json", exclude={"pending_code"}),
        "messages": [m.model_dump(mode="json") for m in msgs],
    }


@router.get("/witness/{phone}/messages")
async def witness_messages(phone: str, key: ReadKey, services: ServicesDep) -> dict[str, Any]:
    msgs = [
        m
        for m in await services.store.list_messages(phone)
        if m.workspace_id in (None, key.workspace_id)
    ]
    return {"data": [m.model_dump(mode="json") for m in msgs]}


@router.get("/sources")
async def sources(key: AdminKey, services: ServicesDep) -> dict[str, Any]:
    keys = await services.store.list_api_keys(key.workspace_id)
    base = services.settings.public_base_url.rstrip("/")
    return {
        "api_base_url": f"{base}/v1",
        "api_keys": [
            ApiKeyPublic.from_key(k).model_dump(mode="json")
            for k in keys
            if k.kind is KeyKind.API_KEY
        ],
        "webhook_signing_secret": workspace_secret(
            services.settings.webhook_signing_secret.get_secret_value(), key.workspace_id
        ),
        "snippets": _snippets(base),
    }


def _snippets(base: str) -> dict[str, str]:
    body = (
        '{"transaction_id":"tx_123","user_id":"usr_9921","amount":4500.00,"currency":"USD",'
        '"type":"CARD_NOT_PRESENT","occurred_at":"2026-10-09T09:14:03Z",'
        '"merchant":{"name":"AutoZone Online","mcc":"5533","country":"US"},'
        '"metadata":{"ip_address":"203.0.113.44","device_fingerprint":"abc-123"},'
        '"witness":{"phone":"+14155550123","allowed_channels":["WHATSAPP","SMS"]}}'
    )
    return {
        "curl": f'curl -X POST {base}/v1/evaluations \\\n  -H "Authorization: Bearer $SUBPOENA_KEY" \\\n'
        f"  -H \"Idempotency-Key: $(uuidgen)\" -H 'Content-Type: application/json' \\\n  -d '{body}'",
        "node": f"const res = await fetch('{base}/v1/evaluations', {{\n  method: 'POST',\n  headers: {{\n"
        "    Authorization: `Bearer ${process.env.SUBPOENA_KEY}`,\n    'Idempotency-Key': crypto.randomUUID(),\n"
        "    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify(transaction),\n});\n"
        "const evaluation = await res.json();",
        "python": f"import httpx, uuid, os\n\nr = httpx.post(\n    '{base}/v1/evaluations',\n"
        "    headers={'Authorization': f\"Bearer {os.environ['SUBPOENA_KEY']}\",\n"
        "             'Idempotency-Key': str(uuid.uuid4())},\n    json=transaction,\n)\nprint(r.json())",
    }


@router.get("/policies")
async def list_policies(key: ReadKey, services: ServicesDep) -> dict[str, Any]:
    await active_policy(services, key.workspace_id)
    policies = await services.store.list_policies(key.workspace_id)
    return {"data": [p.model_dump(mode="json") for p in policies]}


@router.post("/policies", status_code=201)
async def publish_policy(
    body: dict[str, Any], key: AdminKey, services: ServicesDep
) -> dict[str, Any]:
    current = await active_policy(services, key.workspace_id)
    draft = _policy(
        {
            **current.model_dump(mode="json"),
            **body,
            "id": Policy(workspace_id=key.workspace_id).id,
            "workspace_id": key.workspace_id,
            "version": current.version + 1,
            "active": True,
        }
    )
    await services.store.put_policy(draft)
    changed = {
        k: v
        for k, v in draft.model_dump(mode="json", exclude={"id", "version", "created_at"}).items()
        if current.model_dump(mode="json").get(k) != v
    }
    await audit(
        services,
        key,
        "policy.published",
        f"v{draft.version}",
        before={k: current.model_dump(mode="json").get(k) for k in changed},
        after=changed,
    )
    return draft.model_dump(mode="json")


def _policy(data: dict[str, Any]) -> Policy:
    try:
        return Policy.model_validate(data)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        raise ProblemError(
            422, "validation-error", f"{len(errors)} policy field(s) are invalid", errors=errors
        ) from exc


@router.post("/policies/simulate")
async def simulate_policy(
    body: dict[str, Any],
    key: ReadKey,
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> dict[str, Any]:
    """Replay recent courtroom rulings under a draft policy (Spec §10 Policies → Simulate)."""
    current = await active_policy(services, key.workspace_id)
    draft = _policy({**current.model_dump(mode="json"), **body, "workspace_id": key.workspace_id})
    evs = await services.store.list_evaluations(key.workspace_id, EvaluationFilters(), limit, None)
    ruled = [
        e for e in evs if e.p_fraud is not None and e.tier0 and e.tier0.route is Tier0Route.COURT
    ]

    def outcomes(policy: Policy) -> Counter[str]:
        c: Counter[str] = Counter()
        for e in ruled:
            channels = e.witness.allowed_channels if e.witness else []
            assert e.p_fraud is not None
            c[
                decide(
                    e.p_fraud, policy=policy, amount=e.transaction.amount, witness_channels=channels
                ).outcome.value
            ] += 1
        return c

    before, after = outcomes(current), outcomes(draft)
    changed = []
    for e in ruled:
        channels = e.witness.allowed_channels if e.witness else []
        assert e.p_fraud is not None
        a = decide(
            e.p_fraud, policy=current, amount=e.transaction.amount, witness_channels=channels
        ).outcome
        b = decide(
            e.p_fraud, policy=draft, amount=e.transaction.amount, witness_channels=channels
        ).outcome
        if a != b:
            changed.append(
                {"evaluation_id": e.evaluation_id, "p_fraud": e.p_fraud, "from": a, "to": b}
            )
    return {
        "cases": len(ruled),
        "current": dict(before),
        "draft": dict(after),
        "changed": changed[:50],
        "statuses_note": [s.value for s in EvaluationStatus],
    }


@router.get("/demo/scenarios")
async def demo_scenarios(key: ReadKey, services: ServicesDep) -> dict[str, Any]:
    """Seed demo scenarios for the Console's "Send test event" button."""
    if not services.settings.demo_scenarios:
        raise ProblemError(404, "not-found", "Demo scenarios are disabled")
    import json

    path = services.settings.seed_dir / "scenarios.json"
    return {"data": json.loads(path.read_text()) if path.exists() else []}

"""Destinations and their delivery log (Spec §10 Destinations)."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field

from subpoena_schemas import (
    EVENT_TYPES,
    ApiKey,
    Delivery,
    Destination,
    DestinationType,
    Model,
    Scope,
    new_id,
    utcnow,
)

from ..deps import Services, ServicesDep, audit, require
from ..destinations import destination_secret, validate
from ..problems import ProblemError

router = APIRouter(prefix="/v1", tags=["destinations"])
AdminKey = Annotated[ApiKey, Depends(require(Scope.ADMIN))]
HEALTH_WINDOW = 500


class CreateDestination(Model):
    name: str = Field(min_length=1, max_length=100)
    type: DestinationType
    config: dict[str, str]
    enabled_events: list[str] = Field(default_factory=list)


class UpdateDestination(Model):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: dict[str, str] | None = None
    enabled_events: list[str] | None = None
    enabled: bool | None = None


def _events(events: list[str]) -> list[str]:
    unknown = sorted(set(events) - set(EVENT_TYPES))
    if unknown:
        raise ProblemError(422, "validation-error", f"Unknown event types: {', '.join(unknown)}")
    return [e for e in EVENT_TYPES if e in events]


def _config(services: Services, dtype: DestinationType, config: dict[str, str]) -> dict[str, str]:
    try:
        return validate(dtype, config, allow_local=services.settings.env in ("local", "test"))
    except ValueError as exc:
        raise ProblemError(422, "invalid-destination", str(exc)) from exc


def _view(d: Destination, services: Services, *, secret: bool = False) -> dict[str, Any]:
    out = d.model_dump(mode="json", exclude={"workspace_id"})
    if secret and d.type is DestinationType.WEBHOOK:
        out["signing_secret"] = destination_secret(
            services.settings.webhook_signing_secret.get_secret_value(), d.id
        )
    return out


async def _get(services: Services, workspace_id: str, destination_id: str) -> Destination:
    d = await services.store.get_destination(workspace_id, destination_id)
    if d is None:
        raise ProblemError(404, "not-found", f"Destination {destination_id} not found")
    return d


@router.get("/destinations")
async def list_destinations(key: AdminKey, services: ServicesDep) -> dict[str, Any]:
    dests = await services.store.list_destinations(key.workspace_id)
    log = await services.store.list_deliveries(key.workspace_id, HEALTH_WINDOW)
    totals, failed = Counter[str](), Counter[str]()
    last: dict[str, Delivery] = {}
    for row in log:
        totals[row.destination_id] += 1
        failed[row.destination_id] += row.status == "FAILED"
        last.setdefault(row.destination_id, row)
    rows = []
    for d in dests:
        n = totals[d.id]
        rows.append(
            {
                **_view(d, services),
                "deliveries": n,
                "failure_rate": round(failed[d.id] / n, 4) if n else None,
                "last_delivery": last[d.id].model_dump(mode="json") if d.id in last else None,
            }
        )
    return {
        "data": rows,
        "meta": {
            "event_types": list(EVENT_TYPES),
            "bigquery_table": services.settings.bigquery_export_table,
            "pubsub_project": services.settings.gcp_project,
        },
    }


@router.post("/destinations", status_code=201)
async def create_destination(
    body: CreateDestination, key: AdminKey, services: ServicesDep
) -> dict[str, Any]:
    dest = Destination(
        workspace_id=key.workspace_id,
        name=body.name,
        type=body.type,
        config=_config(services, body.type, body.config),
        enabled_events=_events(body.enabled_events),
        created_by=key.name,
    )
    await services.store.put_destination(dest)
    await audit(
        services,
        key,
        "destination.created",
        dest.id,
        after={"name": dest.name, "type": dest.type, "events": dest.enabled_events or "all"},
    )
    return _view(dest, services, secret=True)


@router.get("/destinations/{destination_id}")
async def get_destination(
    destination_id: str, key: AdminKey, services: ServicesDep
) -> dict[str, Any]:
    return _view(await _get(services, key.workspace_id, destination_id), services, secret=True)


@router.patch("/destinations/{destination_id}")
async def update_destination(
    destination_id: str, body: UpdateDestination, key: AdminKey, services: ServicesDep
) -> dict[str, Any]:
    dest = await _get(services, key.workspace_id, destination_id)
    changes: dict[str, Any] = {}
    if body.name is not None:
        changes["name"] = body.name
    if body.config is not None:
        changes["config"] = _config(services, dest.type, body.config)
    if body.enabled_events is not None:
        changes["enabled_events"] = _events(body.enabled_events)
    if body.enabled is not None:
        changes["enabled"] = body.enabled
    updated = dest.model_copy(update=changes)
    await services.store.put_destination(updated)
    await audit(
        services,
        key,
        "destination.updated",
        dest.id,
        before={k: getattr(dest, k) for k in changes},
        after=changes,
    )
    return _view(updated, services)


@router.delete("/destinations/{destination_id}", status_code=204)
async def delete_destination(destination_id: str, key: AdminKey, services: ServicesDep) -> Response:
    dest = await _get(services, key.workspace_id, destination_id)
    await services.store.delete_destination(key.workspace_id, destination_id)
    await audit(
        services, key, "destination.deleted", dest.id, before={"name": dest.name, "type": dest.type}
    )
    return Response(status_code=204)


@router.post("/destinations/{destination_id}/test")
async def test_destination(
    destination_id: str, key: AdminKey, services: ServicesDep
) -> dict[str, Any]:
    """Deliver a sample event right now and return the delivery record."""
    dest = await _get(services, key.workspace_id, destination_id)
    event = {
        "id": new_id("evt"),
        "type": "destination.test",
        "created_at": utcnow().isoformat(),
        "workspace_id": key.workspace_id,
        "data": {
            "evaluation_id": None,
            "transaction_id": None,
            "reason": "Test event from the Console",
        },
        "evaluation": {
            "status": "RULED",
            "verdict": "APPROVE",
            "p_fraud": 0.01,
            "amount": "4500.00",
            "currency": "USD",
            "merchant": "AutoZone Online",
        },
    }
    delivery = await services.notifier.deliver(dest, event)
    return delivery.model_dump(mode="json")


@router.get("/deliveries")
async def list_deliveries(
    key: AdminKey,
    services: ServicesDep,
    destination_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    rows = await services.store.list_deliveries(
        key.workspace_id, HEALTH_WINDOW if destination_id else limit
    )
    if destination_id:
        rows = [r for r in rows if r.destination_id == destination_id]
    return {"data": [r.model_dump(mode="json") for r in rows[:limit]]}

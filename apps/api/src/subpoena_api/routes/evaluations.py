"""Evaluation lifecycle endpoints (Spec §8)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

from subpoena_schemas import (
    Agent,
    ApiKey,
    Evaluation,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationStatus,
    EventType,
    Model,
    Page,
    PageMeta,
    PipelineEvent,
    Scope,
    Tier0Route,
    Verdict,
    utcnow,
)
from subpoena_store import EvaluationFilters, IdempotencyRecord

from ..deps import Services, ServicesDep, active_policy, require
from ..pagination import decode_cursor, encode_cursor
from ..problems import ProblemError
from ..tier0 import prescreen

router = APIRouter(prefix="/v1/evaluations", tags=["evaluations"])

WriteKey = Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_WRITE))]
ReadKey = Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_READ))]

TIER0_VERDICT = {Tier0Route.EXIT_APPROVE: Verdict.APPROVE, Tier0Route.EXIT_BLOCK: Verdict.BLOCK}


@router.post(
    "",
    status_code=202,
    response_model=EvaluationResponse,
    responses={200: {"model": EvaluationResponse, "description": "Resolved at Tier 0"}},
)
async def create_evaluation(
    body: EvaluationRequest,
    key: WriteKey,
    services: ServicesDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=255)] = None,
) -> JSONResponse:
    if not idempotency_key:
        raise ProblemError(400, "idempotency-key-required", "Idempotency-Key header is required")

    request_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    claim = IdempotencyRecord(key.workspace_id, idempotency_key, request_hash, utcnow())
    existing = await services.store.claim_idempotency(claim)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ProblemError(
                422,
                "idempotency-key-reused",
                "Idempotency-Key was already used with a different request body",
            )
        if not existing.completed or existing.body is None or existing.status_code is None:
            raise ProblemError(409, "idempotency-in-progress", "Original request still in progress")
        return JSONResponse(
            existing.body, status_code=existing.status_code, headers={"Idempotent-Replayed": "true"}
        )

    try:
        status_code, payload = await _evaluate(body, key, services)
    except Exception:
        await services.store.release_idempotency(key.workspace_id, idempotency_key)
        raise
    claim.status_code, claim.body = status_code, payload
    await services.store.complete_idempotency(claim)
    return JSONResponse(payload, status_code=status_code)


async def _evaluate(
    body: EvaluationRequest, key: ApiKey, services: Services
) -> tuple[int, dict[str, Any]]:
    policy = await active_policy(services, key.workspace_id)
    txn = body.transaction()
    ev = Evaluation(
        workspace_id=key.workspace_id,
        transaction=txn,
        witness=body.witness,
        options=body.options,
        policy_version=policy.version,
    )
    ev.tier0 = prescreen(txn, services.baselines.get(txn.user_id), policy)
    await services.store.append_event(
        PipelineEvent(
            evaluation_id=ev.evaluation_id,
            sequence=0,
            from_agent=Agent.SYSTEM,
            type=EventType.CASE_OPENED,
            payload={"tier0": ev.tier0.model_dump(mode="json"), "policy_version": policy.version},
        )
    )

    verdict = TIER0_VERDICT.get(ev.tier0.route)
    if verdict is not None:
        now = utcnow()
        ev.status, ev.verdict, ev.ruled_at, ev.updated_at = (
            EvaluationStatus.RULED,
            verdict,
            now,
            now,
        )
        ev.rationale = (
            f"Tier 0 hard rule(s): {', '.join(ev.tier0.rules_hit)}"
            if ev.tier0.rules_hit
            else f"Tier 0 score {ev.tier0.score:.2f} resolved without the courtroom"
        )
        await services.store.put_evaluation(ev)
        await services.store.append_event(
            PipelineEvent(
                evaluation_id=ev.evaluation_id,
                sequence=0,
                from_agent=Agent.SYSTEM,
                type=EventType.VERDICT,
                payload={"verdict": verdict, "tier": 0, "rationale": ev.rationale},
            )
        )
        status_code = 200
    else:
        await services.store.put_evaluation(ev)
        await services.publisher.publish_evaluation_created(ev)
        ev = await _wait_for_courtroom(services, ev)
        status_code = 200 if ev.status in FINAL else 202
    return status_code, EvaluationResponse.from_evaluation(ev).model_dump(mode="json")


FINAL = {EvaluationStatus.RULED, EvaluationStatus.ESCALATED, EvaluationStatus.APPEALED}
PENDING = {EvaluationStatus.RECEIVED, EvaluationStatus.IN_DEBATE}


async def _wait_for_courtroom(services: Services, ev: Evaluation) -> Evaluation:
    """Hold the request up to ``sync_timeout_ms`` so fast courtroom runs answer synchronously."""
    budget = min(ev.options.sync_timeout_ms, services.settings.sync_wait_max_ms) / 1000
    interval = services.settings.sync_poll_interval_ms / 1000
    deadline = asyncio.get_running_loop().time() + budget
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(interval)
        fresh = await services.store.get_evaluation(ev.workspace_id, ev.evaluation_id)
        if fresh is not None:
            ev = fresh
        if ev.status not in PENDING:
            break
    return ev


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(
    evaluation_id: str, key: ReadKey, services: ServicesDep
) -> EvaluationResponse:
    ev = await services.store.get_evaluation(key.workspace_id, evaluation_id)
    if ev is None:
        raise ProblemError(404, "not-found", f"Evaluation {evaluation_id} not found")
    return EvaluationResponse.from_evaluation(ev)


@router.get("", response_model=Page[EvaluationResponse])
async def list_evaluations(
    key: ReadKey,
    services: ServicesDep,
    status: EvaluationStatus | None = None,
    verdict: Verdict | None = None,
    user_id: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    page_token: str | None = None,
) -> Page[EvaluationResponse]:
    after = decode_cursor(page_token) if page_token else None
    filters = EvaluationFilters(status, verdict, user_id, from_, to)
    rows = await services.store.list_evaluations(key.workspace_id, filters, limit + 1, after)
    has_more = len(rows) > limit
    rows = rows[:limit]
    token = (
        encode_cursor(rows[-1].created_at.isoformat(), rows[-1].evaluation_id) if has_more else None
    )
    return Page[EvaluationResponse](
        data=[EvaluationResponse.from_evaluation(r) for r in rows],
        meta=PageMeta(next_page_token=token),
    )


@router.get(
    "/{evaluation_id}/events",
    response_model=Page[PipelineEvent],
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def list_events(
    evaluation_id: str, request: Request, key: ReadKey, services: ServicesDep
) -> Response:
    if await services.store.get_evaluation(key.workspace_id, evaluation_id) is None:
        raise ProblemError(404, "not-found", f"Evaluation {evaluation_id} not found")
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(
            _stream(services, key.workspace_id, evaluation_id, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    events = await services.store.list_events(evaluation_id)
    return JSONResponse(Page[PipelineEvent](data=events, meta=PageMeta()).model_dump(mode="json"))


STREAM_POLL_SECONDS = 0.5
STREAM_MAX_SECONDS = 20 * 60


async def _stream(
    services: Services, workspace_id: str, evaluation_id: str, request: Request
) -> AsyncIterator[str]:
    """Server-sent events: one ``event: pipeline`` per PipelineEvent, then ``event: end``."""
    last = -1
    loop = asyncio.get_running_loop()
    started = idle_since = loop.time()
    while loop.time() - started < STREAM_MAX_SECONDS and not await request.is_disconnected():
        new = await services.store.list_events(evaluation_id, after_sequence=last)
        for e in new:
            last = e.sequence
            yield f"id: {e.sequence}\nevent: pipeline\ndata: {e.model_dump_json()}\n\n"
        if new:
            idle_since = loop.time()
        ev = await services.store.get_evaluation(workspace_id, evaluation_id)
        if ev is not None and ev.status in FINAL and loop.time() - idle_since > 2:
            yield f"event: end\ndata: {json.dumps({'status': ev.status, 'verdict': ev.verdict})}\n\n"
            return
        if loop.time() - idle_since > 15:
            yield ": keep-alive\n\n"
            idle_since = loop.time()
        await asyncio.sleep(STREAM_POLL_SECONDS)


class OverrideRequest(Model):
    verdict: Verdict
    reason: str = Field(min_length=3, max_length=1000)


OverrideKey = Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_OVERRIDE))]


@router.post("/{evaluation_id}/override", response_model=EvaluationResponse)
async def override(
    evaluation_id: str, body: OverrideRequest, key: OverrideKey, services: ServicesDep
) -> EvaluationResponse:
    """Appeals Court: an analyst changes the verdict. The override becomes a training label."""
    ev = await services.store.get_evaluation(key.workspace_id, evaluation_id)
    if ev is None:
        raise ProblemError(404, "not-found", f"Evaluation {evaluation_id} not found")
    if ev.status in PENDING:
        raise ProblemError(409, "case-in-progress", "The courtroom has not ruled yet")
    now = utcnow()
    record = {
        "by": key.name,
        "key_id": key.id,
        "reason": body.reason,
        "verdict": body.verdict,
        "previous_verdict": ev.verdict,
        "previous_status": ev.status,
        "at": now.isoformat(),
    }
    ev = ev.model_copy(
        update={
            "status": EvaluationStatus.APPEALED,
            "verdict": body.verdict,
            "override": record,
            "updated_at": now,
        }
    )
    await services.store.put_evaluation(ev)
    await services.store.append_event(
        PipelineEvent(
            evaluation_id=evaluation_id,
            sequence=0,
            from_agent=Agent.ANALYST,
            type=EventType.OVERRIDE,
            payload=record,
        )
    )
    if body.verdict is not Verdict.HOLD:
        await services.store.put_feedback(
            key.workspace_id,
            {
                "evaluation_id": evaluation_id,
                "transaction_id": ev.transaction.transaction_id,
                "label": "FRAUD" if body.verdict is Verdict.BLOCK else "LEGIT",
                "source": "ANALYST_OVERRIDE",
                "by": key.name,
                "reason": body.reason,
            },
        )
    await services.notifier.notify(
        ev,
        "evaluation.overridden",
        {
            "verdict": body.verdict,
            "previous_verdict": record["previous_verdict"],
            "reason": body.reason,
        },
    )
    return EvaluationResponse.from_evaluation(ev)

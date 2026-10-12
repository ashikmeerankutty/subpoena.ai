"""Precedent library (Spec §10 Precedents): search, "find cases like this", removal."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from subpoena_schemas import ApiKey, Scope
from subpoena_store import case_text
from subpoena_store.precedents import public

from ..deps import ServicesDep, audit, require
from ..problems import ProblemError

router = APIRouter(prefix="/v1", tags=["precedents"])
ReadKey = Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_READ))]
AdminKey = Annotated[ApiKey, Depends(require(Scope.ADMIN))]


@router.get("/precedents")
async def search_precedents(
    key: ReadKey,
    services: ServicesDep,
    q: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    lib = services.precedents
    if q and q.strip():
        hits = await lib.search(key.workspace_id, q.strip(), limit, min_similarity=0.05)
        return {
            "data": [public(p, s) for p, s in hits],
            "meta": {"query": q, "model": lib.embedder.model},
        }
    items = await lib.all(key.workspace_id)
    return {
        "data": [public(p) for p in items[:limit]],
        "meta": {"total": len(items), "model": lib.embedder.model},
    }


@router.get("/evaluations/{evaluation_id}/similar")
async def similar_cases(
    evaluation_id: str,
    key: ReadKey,
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> dict[str, Any]:
    ev = await services.store.get_evaluation(key.workspace_id, evaluation_id)
    if ev is None:
        raise ProblemError(404, "not-found", f"Evaluation {evaluation_id} not found")
    query, _ = case_text(ev, with_outcome=False)
    hits = await services.precedents.search(
        key.workspace_id, query, limit, exclude_evaluation=evaluation_id, min_similarity=0.05
    )
    return {"data": [public(p, s) for p, s in hits], "meta": {"query": query}}


@router.delete("/precedents/{precedent_id}", status_code=204)
async def remove_precedent(precedent_id: str, key: AdminKey, services: ServicesDep) -> Response:
    p = await services.store.get_precedent(key.workspace_id, precedent_id)
    if p is None:
        raise ProblemError(
            404, "not-found", "Precedent not found (shared seed precedents cannot be removed)"
        )
    await services.store.delete_precedent(key.workspace_id, precedent_id)
    await audit(
        services,
        key,
        "precedent.removed",
        precedent_id,
        before={"summary": p.summary, "label": p.label},
    )
    return Response(status_code=204)

"""Precedent library: past rulings as case law, retrieved by embedding similarity.

The shared seed library plus each workspace's own rulings (stored with their embeddings).
Embeddings are computed lazily: a precedent saved without one (or with another model's) is
embedded on the next search and written back, so writers never need model access.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol

from subpoena_schemas import Evaluation, Precedent, PrecedentSource, Verdict

from .base import Store

LABEL = {Verdict.APPROVE: "LEGIT", Verdict.BLOCK: "FRAUD"}


class Embedder(Protocol):
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic bag-of-words vectors (tests, offline). Overlapping words → similar."""

    model = "hash-512"
    dims = 512

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dims
            for tok in re.findall(r"[a-z0-9_]+", text.lower()):
                v[int(hashlib.sha1(tok.encode()).hexdigest(), 16) % self.dims] += 1.0
            out.append(_normalize(v))
        return out


class VertexEmbedder:
    def __init__(self, project: str | None, location: str, model: str) -> None:
        from google import genai

        self.model = model
        self._client = genai.Client(vertexai=True, project=project, location=location)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            batch: list[Any] = texts[i : i + 100]
            r = await self._client.aio.models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
            )
            out += [list(e.values or []) for e in r.embeddings or []]
        return out


def build_embedder(kind: str, project: str | None, location: str, model: str) -> Embedder:
    return VertexEmbedder(project, location, model) if kind == "vertex" else HashEmbedder()


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def case_text(ev: Evaluation, *, with_outcome: bool) -> tuple[str, list[str]]:
    """The searchable description of a case. Queries use the same shape without the outcome."""
    t = ev.transaction
    fraud = sorted({f.type.lower() for f in ev.findings if f.supports == "FRAUD"})
    legit = sorted({f.type.lower() for f in ev.findings if f.supports == "LEGIT"})
    parts = [
        f"{t.type.value.lower().replace('_', ' ')} payment of {t.amount:,.2f} {t.currency} at "
        f"{t.merchant.name} (MCC {t.merchant.mcc}, {t.merchant.country})."
    ]
    if fraud:
        parts.append(f"Fraud signals: {', '.join(fraud)}.")
    if legit:
        parts.append(f"Legitimate signals: {', '.join(legit)}.")
    if with_outcome and ev.testimony:
        c = ev.testimony.claims
        said = {True: "confirmed", False: "denied", None: "did not clearly answer"}[
            c.confirms_transaction
        ]
        parts.append(
            f"The authenticated cardholder {said} it"
            + (f" ({c.stated_reason})" if c.stated_reason else "")
            + "."
        )
        if ev.testimony.receipt:
            parts.append(f"Receipt check: {ev.testimony.receipt.result.value.lower()}.")
    if with_outcome and ev.verdict:
        parts.append(f"Ruled {ev.verdict.value}.")
    text = re.sub(r"[^\w .,:;$()%+-]", " ", " ".join(parts))
    return text, fraud + legit + [f"mcc_{t.merchant.mcc}"]


class PrecedentLibrary:
    def __init__(
        self, store: Store, embedder: Embedder, seed: list[dict[str, Any]] | None = None
    ) -> None:
        self.store = store
        self.embedder = embedder
        self._seed = [
            Precedent(
                id=f"seed_{p['id']}",
                summary=p["summary"],
                verdict=p["verdict"],
                label=p["label"],
                tags=p.get("tags", []),
                source=PrecedentSource.SEED,
            )
            for p in seed or []
        ]
        self._seed_ready = False

    async def _embed_missing(self, items: list[Precedent]) -> None:
        todo = [p for p in items if p.embedding is None or p.embedding_model != self.embedder.model]
        if not todo:
            return
        vectors = await self.embedder.embed([p.summary for p in todo])
        for p, v in zip(todo, vectors, strict=True):
            p.embedding, p.embedding_model = v, self.embedder.model
            if p.workspace_id:
                await self.store.put_precedent(p)

    async def all(self, workspace_id: str) -> list[Precedent]:
        if not self._seed_ready:
            await self._embed_missing(self._seed)
            self._seed_ready = True
        own = await self.store.list_precedents(workspace_id)
        await self._embed_missing(own)
        return own + self._seed

    async def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 3,
        *,
        exclude_evaluation: str | None = None,
        min_similarity: float = 0.2,
    ) -> list[tuple[Precedent, float]]:
        items = [
            p
            for p in await self.all(workspace_id)
            if exclude_evaluation is None or p.evaluation_id != exclude_evaluation
        ]
        if not items:
            return []
        (qv,) = await self.embedder.embed([query])
        scored = [(p, round(cosine(qv, p.embedding or []), 4)) for p in items]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(p, s) for p, s in scored[:limit] if s >= min_similarity]


def precedent_for(
    ev: Evaluation, source: PrecedentSource = PrecedentSource.CASE
) -> Precedent | None:
    """The precedent a ruled courtroom case sets (APPROVE or BLOCK only). Embedded lazily."""
    if ev.verdict not in LABEL or not ev.findings:
        return None
    summary, tags = case_text(ev, with_outcome=True)
    return Precedent(
        id=Precedent.id_for(ev.evaluation_id),
        workspace_id=ev.workspace_id,
        summary=summary,
        verdict=ev.verdict.value,
        label=LABEL[ev.verdict],
        tags=tags,
        source=source,
        evaluation_id=ev.evaluation_id,
    )


def public(p: Precedent, similarity: float | None = None) -> dict[str, Any]:
    out = p.model_dump(mode="json", exclude={"embedding", "workspace_id"})
    if similarity is not None:
        out["similarity"] = similarity
    return out

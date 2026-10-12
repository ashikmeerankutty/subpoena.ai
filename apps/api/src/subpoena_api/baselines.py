"""Read access to user baselines. Locally served from ``data/seed``; BigQuery in demo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from subpoena_schemas import UserBaseline


class BaselineSource(Protocol):
    def get(self, user_id: str) -> UserBaseline | None: ...


class SeedBaselines:
    def __init__(self, seed_dir: Path) -> None:
        path = seed_dir / "baselines.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        self._by_user = {b.user_id: b for b in map(UserBaseline.model_validate, rows)}

    def get(self, user_id: str) -> UserBaseline | None:
        return self._by_user.get(user_id)


class StaticBaselines:
    def __init__(self, baselines: list[UserBaseline]) -> None:
        self._by_user = {b.user_id: b for b in baselines}

    def get(self, user_id: str) -> UserBaseline | None:
        return self._by_user.get(user_id)


class FirestoreBaselines:
    """Baselines mirrored from BigQuery into ``baselines/{user_id}`` for low-latency Tier 0 reads.

    Tier 0 runs inside the request, so reads are cached for the life of the process;
    baselines are recomputed in batch, not per transaction.
    """

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        from google.cloud import firestore

        self._db = firestore.Client(project=project_id, database=database)
        self._cache: dict[str, UserBaseline | None] = {}

    def get(self, user_id: str) -> UserBaseline | None:
        if user_id not in self._cache:
            snap = self._db.collection("baselines").document(user_id).get()
            self._cache[user_id] = (
                UserBaseline.model_validate(snap.to_dict()) if snap.exists else None
            )
        return self._cache[user_id]

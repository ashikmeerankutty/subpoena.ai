"""Firestore-backed ``Store`` (Spec §9: live case state).

Layout
  workspaces/{workspace_id}
  workspaces/{workspace_id}/policies/{policy_id}
  api_keys/{key_id}                      queried by ``hash``
  evaluations/{evaluation_id}            + ``_created_at`` timestamp for ordering/filtering
  evaluations/{evaluation_id}/events/{sequence:06d}
  idempotency/{sha256(workspace_id:key)}
  subpoenas/{subpoena_id}                + ``_sent_at`` timestamp
  witness_messages/{message_id}          + ``_created_at`` timestamp
  verifications/{phone}                  simulated Verify codes (hash only)
  feedback/{id}

Documents are stored in Pydantic's JSON mode (Decimals and datetimes as strings), so
reading back is a plain ``model_validate``. Fields used in queries get native copies.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from subpoena_schemas import (
    ApiKey,
    Evaluation,
    PipelineEvent,
    Policy,
    Subpoena,
    SubpoenaState,
    WitnessMessage,
    Workspace,
    new_id,
    utcnow,
)

from .base import EvaluationFilters, IdempotencyRecord, Verification

ORDER_FIELD = "_created_at"
EVENT_CREATE_ATTEMPTS = 20
EVENT_CACHE_SIZE = 10_000


def _doc(model: Any) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def _strip(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    return {k: v for k, v in data.items() if not k.startswith("_")}


class FirestoreStore:
    def __init__(
        self,
        client: firestore.AsyncClient,
        idempotency_ttl: timedelta = timedelta(hours=24),
    ) -> None:
        self._db = client
        self._idem_ttl = idempotency_ttl
        self._next_seq: dict[str, int] = {}
        self._event_locks: dict[str, asyncio.Lock] = {}

    # Workspaces & policies -------------------------------------------------------------

    async def put_workspace(self, ws: Workspace) -> None:
        await self._db.collection("workspaces").document(ws.id).set(_doc(ws))

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        snap = await self._db.collection("workspaces").document(workspace_id).get()
        return Workspace.model_validate(snap.to_dict()) if snap.exists else None

    def _policies(self, workspace_id: str) -> firestore.AsyncCollectionReference:
        col: firestore.AsyncCollectionReference = (
            self._db.collection("workspaces").document(workspace_id).collection("policies")
        )
        return col

    async def put_policy(self, policy: Policy) -> None:
        col = self._policies(policy.workspace_id)
        batch = self._db.batch()
        if policy.active:
            async for snap in col.where(
                filter=firestore.FieldFilter("active", "==", True)
            ).stream():
                if snap.id != policy.id:
                    batch.update(snap.reference, {"active": False})
        batch.set(col.document(policy.id), _doc(policy))
        await batch.commit()

    async def get_active_policy(self, workspace_id: str) -> Policy | None:
        query = self._policies(workspace_id).where(
            filter=firestore.FieldFilter("active", "==", True)
        )
        policies = [Policy.model_validate(s.to_dict()) async for s in query.stream()]
        return max(policies, key=lambda p: p.version, default=None)

    async def list_policies(self, workspace_id: str) -> list[Policy]:
        policies = [
            Policy.model_validate(s.to_dict()) async for s in self._policies(workspace_id).stream()
        ]
        return sorted(policies, key=lambda p: p.version, reverse=True)

    # API keys --------------------------------------------------------------------------

    async def put_api_key(self, key: ApiKey) -> None:
        await self._db.collection("api_keys").document(key.id).set(_doc(key))

    async def get_api_key(self, workspace_id: str, key_id: str) -> ApiKey | None:
        snap = await self._db.collection("api_keys").document(key_id).get()
        if not snap.exists:
            return None
        key = ApiKey.model_validate(snap.to_dict())
        return key if key.workspace_id == workspace_id else None

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        query = (
            self._db.collection("api_keys")
            .where(filter=firestore.FieldFilter("hash", "==", key_hash))
            .limit(1)
        )
        async for snap in query.stream():
            return ApiKey.model_validate(snap.to_dict())
        return None

    async def list_api_keys(self, workspace_id: str) -> list[ApiKey]:
        query = self._db.collection("api_keys").where(
            filter=firestore.FieldFilter("workspace_id", "==", workspace_id)
        )
        keys = [ApiKey.model_validate(s.to_dict()) async for s in query.stream()]
        return sorted(keys, key=lambda k: k.created_at, reverse=True)

    # Evaluations -----------------------------------------------------------------------

    async def put_evaluation(self, ev: Evaluation) -> None:
        data = _doc(ev) | {ORDER_FIELD: ev.created_at}
        await self._db.collection("evaluations").document(ev.evaluation_id).set(data)

    async def get_evaluation(self, workspace_id: str, evaluation_id: str) -> Evaluation | None:
        snap = await self._db.collection("evaluations").document(evaluation_id).get()
        if not snap.exists:
            return None
        ev = Evaluation.model_validate(_strip(snap.to_dict()))
        return ev if ev.workspace_id == workspace_id else None

    async def get_evaluation_any(self, evaluation_id: str) -> Evaluation | None:
        snap = await self._db.collection("evaluations").document(evaluation_id).get()
        return Evaluation.model_validate(_strip(snap.to_dict())) if snap.exists else None

    async def list_evaluations(
        self,
        workspace_id: str,
        filters: EvaluationFilters,
        limit: int,
        after: tuple[str, str] | None,
    ) -> list[Evaluation]:
        def eq(field: str, value: Any) -> firestore.FieldFilter:
            return firestore.FieldFilter(field, "==", value)

        query = self._db.collection("evaluations").where(filter=eq("workspace_id", workspace_id))
        if filters.status is not None:
            query = query.where(filter=eq("status", filters.status.value))
        if filters.verdict is not None:
            query = query.where(filter=eq("verdict", filters.verdict.value))
        if filters.user_id is not None:
            query = query.where(filter=eq("transaction.user_id", filters.user_id))
        if filters.created_from is not None:
            query = query.where(
                filter=firestore.FieldFilter(ORDER_FIELD, ">=", filters.created_from)
            )
        if filters.created_to is not None:
            query = query.where(filter=firestore.FieldFilter(ORDER_FIELD, "<", filters.created_to))
        query = query.order_by(ORDER_FIELD, direction=firestore.Query.DESCENDING).order_by(
            "evaluation_id", direction=firestore.Query.DESCENDING
        )
        if after is not None:
            query = query.start_after(
                {ORDER_FIELD: datetime.fromisoformat(after[0]), "evaluation_id": after[1]}
            )
        return [
            Evaluation.model_validate(_strip(s.to_dict()))
            async for s in query.limit(limit).stream()
        ]

    # Pipeline events -------------------------------------------------------------------

    def _events(self, evaluation_id: str) -> firestore.AsyncCollectionReference:
        col: firestore.AsyncCollectionReference = (
            self._db.collection("evaluations").document(evaluation_id).collection("events")
        )
        return col

    async def _last_sequence(self, evaluation_id: str) -> int:
        query = (
            self._events(evaluation_id)
            .order_by("sequence", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        async for snap in query.stream():
            return int(snap.get("sequence"))
        return -1

    async def append_event(self, event: PipelineEvent) -> PipelineEvent:
        # Optimistic numbering: ``create`` on ``events/{seq}`` is atomic, so a clash with
        # another process just moves on to the next number. Within this process a
        # per-evaluation lock and cached counter mean clashes don't happen at all.
        eid = event.evaluation_id
        lock = self._event_locks.setdefault(eid, asyncio.Lock())
        async with lock:
            seq = self._next_seq.get(eid)
            if seq is None:
                seq = await self._last_sequence(eid) + 1
            for _ in range(EVENT_CREATE_ATTEMPTS):
                stored = event.model_copy(update={"sequence": seq})
                try:
                    await self._events(eid).document(f"{seq:06d}").create(_doc(stored))
                except AlreadyExists:
                    seq = await self._last_sequence(eid) + 1
                    continue
                self._next_seq[eid] = seq + 1
                self._trim_event_cache()
                return stored
        raise RuntimeError(f"could not append event to {eid} after {EVENT_CREATE_ATTEMPTS} tries")

    def _trim_event_cache(self) -> None:
        while len(self._next_seq) > EVENT_CACHE_SIZE:
            oldest = next(iter(self._next_seq))
            self._next_seq.pop(oldest)
            lock = self._event_locks.get(oldest)
            if lock is not None and not lock.locked():
                self._event_locks.pop(oldest)

    async def list_events(
        self, evaluation_id: str, after_sequence: int = -1
    ) -> list[PipelineEvent]:
        query = self._events(evaluation_id).order_by("sequence")
        if after_sequence >= 0:
            query = query.where(filter=firestore.FieldFilter("sequence", ">", after_sequence))
        return [PipelineEvent.model_validate(s.to_dict()) async for s in query.stream()]

    # Idempotency -----------------------------------------------------------------------

    def _idem_ref(self, workspace_id: str, key: str) -> firestore.AsyncDocumentReference:
        doc_id = hashlib.sha256(f"{workspace_id}:{key}".encode()).hexdigest()
        return self._db.collection("idempotency").document(doc_id)

    @staticmethod
    def _idem_doc(r: IdempotencyRecord) -> dict[str, Any]:
        return {
            "workspace_id": r.workspace_id,
            "key": r.key,
            "request_hash": r.request_hash,
            "created_at": r.created_at,
            "status_code": r.status_code,
            "body": r.body,
        }

    async def claim_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord | None:
        ref = self._idem_ref(record.workspace_id, record.key)
        try:
            await ref.create(self._idem_doc(record))
            return None
        except AlreadyExists:
            pass

        @firestore.async_transactional
        async def txn(transaction: firestore.AsyncTransaction) -> IdempotencyRecord | None:
            snap = await ref.get(transaction=transaction)
            data = snap.to_dict() if snap.exists else None
            if data and utcnow() - data["created_at"] < self._idem_ttl:
                return IdempotencyRecord(**data)
            transaction.set(ref, self._idem_doc(record))
            return None

        result: IdempotencyRecord | None = await txn(self._db.transaction())
        return result

    async def complete_idempotency(self, record: IdempotencyRecord) -> None:
        await self._idem_ref(record.workspace_id, record.key).set(self._idem_doc(record))

    async def release_idempotency(self, workspace_id: str, key: str) -> None:
        await self._idem_ref(workspace_id, key).delete()

    # Subpoenas & witness conversation ----------------------------------------------------

    async def put_subpoena(self, subpoena: Subpoena) -> None:
        data = _doc(subpoena) | {"_sent_at": subpoena.sent_at}
        await self._db.collection("subpoenas").document(subpoena.id).set(data)

    async def get_subpoena(self, subpoena_id: str) -> Subpoena | None:
        snap = await self._db.collection("subpoenas").document(subpoena_id).get()
        return Subpoena.model_validate(_strip(snap.to_dict())) if snap.exists else None

    async def find_open_subpoena(self, phone: str) -> Subpoena | None:
        query = (
            self._db.collection("subpoenas")
            .where(filter=firestore.FieldFilter("phone", "==", phone))
            .where(filter=firestore.FieldFilter("state", "==", SubpoenaState.AWAITING_REPLY.value))
        )
        rows = [Subpoena.model_validate(_strip(s.to_dict())) async for s in query.stream()]
        return max(rows, key=lambda s: s.sent_at, default=None)

    async def list_subpoenas(self, workspace_id: str, limit: int) -> list[Subpoena]:
        query = self._db.collection("subpoenas").where(
            filter=firestore.FieldFilter("workspace_id", "==", workspace_id)
        )
        rows = [Subpoena.model_validate(_strip(s.to_dict())) async for s in query.stream()]
        return sorted(rows, key=lambda s: s.sent_at, reverse=True)[:limit]

    async def put_message(self, message: WitnessMessage) -> None:
        data = _doc(message) | {"_created_at": message.created_at}
        await self._db.collection("witness_messages").document(message.id).set(data)

    async def update_message_status(self, sid: str, status: str) -> None:
        query = self._db.collection("witness_messages").where(
            filter=firestore.FieldFilter("sid", "==", sid)
        )
        async for snap in query.stream():
            await snap.reference.update({"status": status})

    async def list_messages(self, phone: str, limit: int = 100) -> list[WitnessMessage]:
        query = self._db.collection("witness_messages").where(
            filter=firestore.FieldFilter("phone", "==", phone)
        )
        rows = [WitnessMessage.model_validate(_strip(s.to_dict())) async for s in query.stream()]
        return sorted(rows, key=lambda m: m.created_at)[-limit:]

    # Simulated Verify --------------------------------------------------------------------

    async def put_verification(self, v: Verification) -> None:
        await (
            self._db.collection("verifications")
            .document(v.phone)
            .set(
                {
                    "phone": v.phone,
                    "code_hash": v.code_hash,
                    "expires_at": v.expires_at,
                    "attempts": v.attempts,
                }
            )
        )

    async def get_verification(self, phone: str) -> Verification | None:
        snap = await self._db.collection("verifications").document(phone).get()
        data = snap.to_dict()
        return Verification(**data) if snap.exists and data else None

    async def delete_verification(self, phone: str) -> None:
        await self._db.collection("verifications").document(phone).delete()

    # Labels ------------------------------------------------------------------------------

    async def put_feedback(self, workspace_id: str, record: dict[str, Any]) -> None:
        data = {"workspace_id": workspace_id, "created_at": utcnow(), **record}
        await self._db.collection("feedback").document(new_id("fb")).set(data)

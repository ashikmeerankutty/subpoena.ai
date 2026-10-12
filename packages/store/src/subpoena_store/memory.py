from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta
from typing import Any

from subpoena_schemas import (
    ApiKey,
    AuditEntry,
    Delivery,
    DeliveryStatus,
    Destination,
    Evaluation,
    Member,
    PipelineEvent,
    Policy,
    Precedent,
    Subpoena,
    SubpoenaState,
    WitnessMessage,
    Workspace,
    utcnow,
)

from .base import EvaluationFilters, IdempotencyRecord, Verification


class MemoryStore:
    def __init__(self, idempotency_ttl: timedelta = timedelta(hours=24)) -> None:
        self._workspaces: dict[str, Workspace] = {}
        self._policies: dict[str, list[Policy]] = defaultdict(list)
        self._keys: dict[str, ApiKey] = {}
        self._evals: dict[str, Evaluation] = {}
        self._events: dict[str, list[PipelineEvent]] = defaultdict(list)
        self._idem: dict[tuple[str, str], IdempotencyRecord] = {}
        self._idem_ttl = idempotency_ttl
        self._subpoenas: dict[str, Subpoena] = {}
        self._messages: list[WitnessMessage] = []
        self._verifications: dict[str, Verification] = {}
        self.feedback: list[dict[str, Any]] = []
        self._members: dict[str, Member] = {}
        self._audit: list[AuditEntry] = []
        self._destinations: dict[str, Destination] = {}
        self._deliveries: list[Delivery] = []
        self._precedents: dict[str, Precedent] = {}
        self._lock = asyncio.Lock()

    async def put_workspace(self, ws: Workspace) -> None:
        self._workspaces[ws.id] = ws

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self._workspaces.get(workspace_id)

    async def put_policy(self, policy: Policy) -> None:
        versions = self._policies[policy.workspace_id]
        if policy.active:
            for i, p in enumerate(versions):
                if p.active:
                    versions[i] = p.model_copy(update={"active": False})
        versions.append(policy)

    async def get_active_policy(self, workspace_id: str) -> Policy | None:
        return next((p for p in reversed(self._policies[workspace_id]) if p.active), None)

    async def list_policies(self, workspace_id: str) -> list[Policy]:
        return sorted(self._policies[workspace_id], key=lambda p: p.version, reverse=True)

    async def put_api_key(self, key: ApiKey) -> None:
        self._keys[key.id] = key

    async def get_api_key(self, workspace_id: str, key_id: str) -> ApiKey | None:
        key = self._keys.get(key_id)
        return key if key and key.workspace_id == workspace_id else None

    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        return next((k for k in self._keys.values() if k.hash == key_hash), None)

    async def list_api_keys(self, workspace_id: str) -> list[ApiKey]:
        keys = [k for k in self._keys.values() if k.workspace_id == workspace_id]
        return sorted(keys, key=lambda k: k.created_at, reverse=True)

    async def put_evaluation(self, ev: Evaluation) -> None:
        self._evals[ev.evaluation_id] = ev

    async def get_evaluation(self, workspace_id: str, evaluation_id: str) -> Evaluation | None:
        ev = self._evals.get(evaluation_id)
        return ev if ev and ev.workspace_id == workspace_id else None

    async def get_evaluation_any(self, evaluation_id: str) -> Evaluation | None:
        return self._evals.get(evaluation_id)

    async def list_evaluations(
        self,
        workspace_id: str,
        filters: EvaluationFilters,
        limit: int,
        after: tuple[str, str] | None,
    ) -> list[Evaluation]:
        def keep(ev: Evaluation) -> bool:
            f = filters
            return (
                ev.workspace_id == workspace_id
                and (f.status is None or ev.status == f.status)
                and (f.verdict is None or ev.verdict == f.verdict)
                and (f.user_id is None or ev.transaction.user_id == f.user_id)
                and (f.created_from is None or ev.created_at >= f.created_from)
                and (f.created_to is None or ev.created_at < f.created_to)
                and (after is None or (ev.created_at.isoformat(), ev.evaluation_id) < after)
            )

        rows = sorted(
            filter(keep, self._evals.values()),
            key=lambda e: (e.created_at.isoformat(), e.evaluation_id),
            reverse=True,
        )
        return rows[:limit]

    async def append_event(self, event: PipelineEvent) -> PipelineEvent:
        async with self._lock:
            events = self._events[event.evaluation_id]
            stored = event.model_copy(update={"sequence": len(events)})
            events.append(stored)
            return stored

    async def list_events(
        self, evaluation_id: str, after_sequence: int = -1
    ) -> list[PipelineEvent]:
        return [e for e in self._events[evaluation_id] if e.sequence > after_sequence]

    async def claim_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord | None:
        async with self._lock:
            k = (record.workspace_id, record.key)
            existing = self._idem.get(k)
            if existing and utcnow() - existing.created_at < self._idem_ttl:
                return existing
            self._idem[k] = record
            return None

    async def complete_idempotency(self, record: IdempotencyRecord) -> None:
        self._idem[(record.workspace_id, record.key)] = record

    async def release_idempotency(self, workspace_id: str, key: str) -> None:
        self._idem.pop((workspace_id, key), None)

    async def put_subpoena(self, subpoena: Subpoena) -> None:
        self._subpoenas[subpoena.id] = subpoena

    async def get_subpoena(self, subpoena_id: str) -> Subpoena | None:
        return self._subpoenas.get(subpoena_id)

    async def find_open_subpoena(self, phone: str) -> Subpoena | None:
        open_ = [
            s
            for s in self._subpoenas.values()
            if s.phone == phone and s.state is SubpoenaState.AWAITING_REPLY
        ]
        return max(open_, key=lambda s: s.sent_at, default=None)

    async def list_subpoenas(self, workspace_id: str, limit: int) -> list[Subpoena]:
        rows = [s for s in self._subpoenas.values() if s.workspace_id == workspace_id]
        return sorted(rows, key=lambda s: s.sent_at, reverse=True)[:limit]

    async def put_message(self, message: WitnessMessage) -> None:
        self._messages.append(message)

    async def update_message_status(self, sid: str, status: str) -> None:
        for i, m in enumerate(self._messages):
            if m.sid == sid:
                self._messages[i] = m.model_copy(update={"status": DeliveryStatus(status)})

    async def list_messages(self, phone: str, limit: int = 100) -> list[WitnessMessage]:
        rows = [m for m in self._messages if m.phone == phone]
        return sorted(rows, key=lambda m: m.created_at)[-limit:]

    async def put_verification(self, v: Verification) -> None:
        self._verifications[v.phone] = v

    async def get_verification(self, phone: str) -> Verification | None:
        return self._verifications.get(phone)

    async def delete_verification(self, phone: str) -> None:
        self._verifications.pop(phone, None)

    async def put_feedback(self, workspace_id: str, record: dict[str, Any]) -> None:
        self.feedback.append({"workspace_id": workspace_id, **record})

    async def put_member(self, member: Member) -> None:
        self._members[member.id] = member

    async def get_member(self, workspace_id: str, member_id: str) -> Member | None:
        m = self._members.get(member_id)
        return m if m and m.workspace_id == workspace_id else None

    async def list_members(self, workspace_id: str) -> list[Member]:
        rows = [m for m in self._members.values() if m.workspace_id == workspace_id]
        return sorted(rows, key=lambda m: m.created_at)

    async def find_members_by_email(self, email: str) -> list[Member]:
        return [m for m in self._members.values() if m.email == email.lower()]

    async def delete_member(self, workspace_id: str, member_id: str) -> None:
        if await self.get_member(workspace_id, member_id):
            del self._members[member_id]

    async def append_audit(self, entry: AuditEntry) -> None:
        self._audit.append(entry)

    async def list_audit(self, workspace_id: str, limit: int) -> list[AuditEntry]:
        rows = [a for a in self._audit if a.workspace_id == workspace_id]
        return sorted(rows, key=lambda a: a.at, reverse=True)[:limit]

    async def put_destination(self, dest: Destination) -> None:
        self._destinations[dest.id] = dest

    async def get_destination(self, workspace_id: str, destination_id: str) -> Destination | None:
        d = self._destinations.get(destination_id)
        return d if d and d.workspace_id == workspace_id else None

    async def list_destinations(self, workspace_id: str) -> list[Destination]:
        rows = [d for d in self._destinations.values() if d.workspace_id == workspace_id]
        return sorted(rows, key=lambda d: d.created_at)

    async def delete_destination(self, workspace_id: str, destination_id: str) -> None:
        if await self.get_destination(workspace_id, destination_id):
            del self._destinations[destination_id]

    async def append_delivery(self, delivery: Delivery) -> None:
        self._deliveries.append(delivery)

    async def list_deliveries(self, workspace_id: str, limit: int) -> list[Delivery]:
        rows = [d for d in self._deliveries if d.workspace_id == workspace_id]
        return sorted(rows, key=lambda d: d.at, reverse=True)[:limit]

    async def put_precedent(self, precedent: Precedent) -> None:
        assert precedent.workspace_id
        self._precedents[precedent.id] = precedent

    async def get_precedent(self, workspace_id: str, precedent_id: str) -> Precedent | None:
        p = self._precedents.get(precedent_id)
        return p if p and p.workspace_id == workspace_id else None

    async def list_precedents(self, workspace_id: str) -> list[Precedent]:
        rows = [p for p in self._precedents.values() if p.workspace_id == workspace_id]
        return sorted(rows, key=lambda p: p.created_at, reverse=True)

    async def delete_precedent(self, workspace_id: str, precedent_id: str) -> None:
        if await self.get_precedent(workspace_id, precedent_id):
            del self._precedents[precedent_id]

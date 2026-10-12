"""Persistence interface. ``MemoryStore`` backs local dev/tests; Firestore backs demo/prod."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from subpoena_schemas import (
    ApiKey,
    AuditEntry,
    Evaluation,
    EvaluationStatus,
    Member,
    PipelineEvent,
    Policy,
    Subpoena,
    Verdict,
    WitnessMessage,
    Workspace,
)


@dataclass(frozen=True)
class EvaluationFilters:
    status: EvaluationStatus | None = None
    verdict: Verdict | None = None
    user_id: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


@dataclass
class Verification:
    """A one-time code issued by the simulated Verify service (real Twilio keeps its own)."""

    phone: str
    code_hash: str
    expires_at: datetime
    attempts: int = 0


@dataclass
class IdempotencyRecord:
    workspace_id: str
    key: str
    request_hash: str
    created_at: datetime
    status_code: int | None = None
    body: dict[str, Any] | None = None

    @property
    def completed(self) -> bool:
        return self.status_code is not None


class Store(Protocol):
    # Workspaces & policies
    async def put_workspace(self, ws: Workspace) -> None: ...
    async def get_workspace(self, workspace_id: str) -> Workspace | None: ...
    async def put_policy(self, policy: Policy) -> None: ...
    async def get_active_policy(self, workspace_id: str) -> Policy | None: ...
    async def list_policies(self, workspace_id: str) -> list[Policy]: ...

    # API keys
    async def put_api_key(self, key: ApiKey) -> None: ...
    async def get_api_key(self, workspace_id: str, key_id: str) -> ApiKey | None: ...
    async def get_api_key_by_hash(self, key_hash: str) -> ApiKey | None: ...
    async def list_api_keys(self, workspace_id: str) -> list[ApiKey]: ...

    # Evaluations
    async def put_evaluation(self, ev: Evaluation) -> None: ...
    async def get_evaluation(self, workspace_id: str, evaluation_id: str) -> Evaluation | None: ...
    async def get_evaluation_any(self, evaluation_id: str) -> Evaluation | None:
        """Unscoped lookup for trusted internal services (courtroom, MCP); never for API callers."""
        ...

    async def list_evaluations(
        self,
        workspace_id: str,
        filters: EvaluationFilters,
        limit: int,
        after: tuple[str, str] | None,
    ) -> list[Evaluation]:
        """Newest first; ``after`` is the (created_at ISO, evaluation_id) of the last item seen."""
        ...

    # Pipeline events
    async def append_event(self, event: PipelineEvent) -> PipelineEvent:
        """Persist ``event`` and return it with its per-evaluation ``sequence`` assigned."""
        ...

    async def list_events(
        self, evaluation_id: str, after_sequence: int = -1
    ) -> list[PipelineEvent]: ...

    # Idempotency
    async def claim_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord | None:
        """Insert ``record`` unless a live one exists for the same key; return the existing one."""
        ...

    async def complete_idempotency(self, record: IdempotencyRecord) -> None: ...
    async def release_idempotency(self, workspace_id: str, key: str) -> None: ...

    # Subpoenas & witness conversation
    async def put_subpoena(self, subpoena: Subpoena) -> None: ...
    async def get_subpoena(self, subpoena_id: str) -> Subpoena | None: ...
    async def find_open_subpoena(self, phone: str) -> Subpoena | None:
        """Most recent subpoena awaiting a reply from ``phone``."""
        ...

    async def list_subpoenas(self, workspace_id: str, limit: int) -> list[Subpoena]: ...
    async def put_message(self, message: WitnessMessage) -> None: ...
    async def update_message_status(self, sid: str, status: str) -> None: ...
    async def list_messages(self, phone: str, limit: int = 100) -> list[WitnessMessage]: ...

    # Simulated Verify
    async def put_verification(self, v: Verification) -> None: ...
    async def get_verification(self, phone: str) -> Verification | None: ...
    async def delete_verification(self, phone: str) -> None: ...

    # Labels
    async def put_feedback(self, workspace_id: str, record: dict[str, Any]) -> None: ...

    # Members (Console users)
    async def put_member(self, member: Member) -> None: ...
    async def get_member(self, workspace_id: str, member_id: str) -> Member | None: ...
    async def list_members(self, workspace_id: str) -> list[Member]: ...
    async def find_members_by_email(self, email: str) -> list[Member]:
        """Every workspace membership of ``email`` (lower-cased), for sign-in."""
        ...

    async def delete_member(self, workspace_id: str, member_id: str) -> None: ...

    # Audit log (append-only)
    async def append_audit(self, entry: AuditEntry) -> None: ...
    async def list_audit(self, workspace_id: str, limit: int) -> list[AuditEntry]:
        """Newest first."""
        ...

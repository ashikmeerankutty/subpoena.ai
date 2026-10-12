"""Request dependencies: app services and API-key authentication."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Request

from subpoena_schemas import Actor, ApiKey, AuditEntry, Policy, Role, Scope, role_for, utcnow
from subpoena_store import (
    HashEmbedder,
    MediaStore,
    MemoryMediaStore,
    MemoryStore,
    PrecedentLibrary,
    Store,
)

from .baselines import BaselineSource
from .problems import ProblemError
from .publisher import Publisher
from .security import hash_secret
from .settings import Settings
from .webhooks import BankNotifier

LAST_USED_RESOLUTION = timedelta(minutes=1)

# Verifies a Google ID token and returns its claims (raises ValueError if invalid).
GoogleVerifier = Callable[[str], Awaitable[dict[str, Any]]]


@dataclass
class Services:
    settings: Settings
    store: Store
    publisher: Publisher
    baselines: BaselineSource
    notifier: BankNotifier
    google_verifier: GoogleVerifier | None = None
    media: MediaStore = field(default_factory=MemoryMediaStore)
    precedents: PrecedentLibrary = field(
        default_factory=lambda: PrecedentLibrary(MemoryStore(), HashEmbedder())
    )


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


async def authenticate(request: Request, services: ServicesDep) -> ApiKey:
    challenge = {"WWW-Authenticate": "Bearer"}
    header = request.headers.get("authorization", "")
    scheme, _, secret = header.partition(" ")
    if scheme.lower() != "bearer" or not secret:
        raise ProblemError(401, "unauthenticated", "Missing bearer API key", headers=challenge)
    pepper = services.settings.api_key_pepper.get_secret_value()
    key = await services.store.get_api_key_by_hash(hash_secret(secret.strip(), pepper))
    now = utcnow()
    if key is None or key.revoked_at is not None or (key.expires_at and key.expires_at <= now):
        raise ProblemError(401, "unauthenticated", "Invalid or revoked API key", headers=challenge)
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_RESOLUTION:
        key = key.model_copy(update={"last_used_at": now})
        await services.store.put_api_key(key)
    if role_for(key.scopes) is Role.VIEWER:
        ws = await services.store.get_workspace(key.workspace_id)
        # Read by ``pii.MaskPiiMiddleware`` once the response is ready.
        request.state.mask_pii = ws is None or ws.settings.pii_masking
    return key


def require(scope: Scope) -> Callable[..., Coroutine[Any, Any, ApiKey]]:
    async def dep(key: Annotated[ApiKey, Depends(authenticate)]) -> ApiKey:
        if scope not in key.scopes and Scope.ADMIN not in key.scopes:
            raise ProblemError(403, "insufficient-scope", f"API key lacks scope '{scope}'")
        return key

    return dep


async def active_policy(services: Services, workspace_id: str) -> Policy:
    policy = await services.store.get_active_policy(workspace_id)
    if policy is None:
        policy = Policy(workspace_id=workspace_id)
        await services.store.put_policy(policy)
    return policy


async def audit(
    services: Services,
    key: ApiKey,
    action: str,
    target: str | None = None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    await services.store.append_audit(
        AuditEntry(
            workspace_id=key.workspace_id,
            actor=Actor.of(key),
            action=action,
            target=target,
            before=before,
            after=after,
        )
    )

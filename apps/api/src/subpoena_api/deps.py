"""Request dependencies: app services and API-key authentication."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Request

from subpoena_schemas import ApiKey, Policy, Scope, utcnow
from subpoena_store import Store

from .baselines import BaselineSource
from .problems import ProblemError
from .publisher import Publisher
from .security import hash_secret
from .settings import Settings
from .webhooks import BankNotifier

LAST_USED_RESOLUTION = timedelta(minutes=1)


@dataclass
class Services:
    settings: Settings
    store: Store
    publisher: Publisher
    baselines: BaselineSource
    notifier: BankNotifier


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
    if key is None or key.revoked_at is not None:
        raise ProblemError(401, "unauthenticated", "Invalid or revoked API key", headers=challenge)
    now = utcnow()
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_RESOLUTION:
        key = key.model_copy(update={"last_used_at": now})
        await services.store.put_api_key(key)
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

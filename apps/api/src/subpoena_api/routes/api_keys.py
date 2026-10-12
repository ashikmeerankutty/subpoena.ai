"""API key management (Spec §8, Console → Sources). Secrets are returned exactly once."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from subpoena_schemas import (
    ApiKey,
    ApiKeyCreated,
    ApiKeyPublic,
    KeyKind,
    Model,
    Page,
    PageMeta,
    Scope,
    utcnow,
)

from ..deps import Services, ServicesDep, audit, require
from ..problems import ProblemError
from ..security import display_prefix, generate_secret, hash_secret

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])

AdminKey = Annotated[ApiKey, Depends(require(Scope.ADMIN))]


class CreateApiKey(Model):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(
        default_factory=lambda: [Scope.EVALUATIONS_WRITE, Scope.EVALUATIONS_READ], min_length=1
    )


async def issue_key(
    services: Services, workspace_id: str, name: str, scopes: list[Scope], created_by: str | None
) -> ApiKeyCreated:
    secret = generate_secret(services.settings.key_mode)
    key = ApiKey(
        workspace_id=workspace_id,
        name=name,
        prefix=display_prefix(secret),
        hash=hash_secret(secret, services.settings.api_key_pepper.get_secret_value()),
        scopes=scopes,
        created_by=created_by,
    )
    await services.store.put_api_key(key)
    return ApiKeyCreated(**ApiKeyPublic.from_key(key).model_dump(), secret=secret)


@router.get("", response_model=Page[ApiKeyPublic])
async def list_keys(key: AdminKey, services: ServicesDep) -> Page[ApiKeyPublic]:
    keys = await services.store.list_api_keys(key.workspace_id)
    return Page[ApiKeyPublic](
        data=[ApiKeyPublic.from_key(k) for k in keys if k.kind is KeyKind.API_KEY], meta=PageMeta()
    )


@router.post("", status_code=201, response_model=ApiKeyCreated)
async def create_key(body: CreateApiKey, key: AdminKey, services: ServicesDep) -> ApiKeyCreated:
    created = await issue_key(
        services, key.workspace_id, body.name, body.scopes, created_by=key.name
    )
    await audit(
        services,
        key,
        "api_key.created",
        created.id,
        after={"name": created.name, "prefix": created.prefix, "scopes": created.scopes},
    )
    return created


@router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: str, key: AdminKey, services: ServicesDep) -> Response:
    target = await services.store.get_api_key(key.workspace_id, key_id)
    if target is None or target.kind is not KeyKind.API_KEY:
        raise ProblemError(404, "not-found", f"API key {key_id} not found")
    if target.revoked_at is None:
        await services.store.put_api_key(target.model_copy(update={"revoked_at": utcnow()}))
        await audit(
            services,
            key,
            "api_key.revoked",
            key_id,
            before={"name": target.name, "prefix": target.prefix},
        )
    return Response(status_code=204)

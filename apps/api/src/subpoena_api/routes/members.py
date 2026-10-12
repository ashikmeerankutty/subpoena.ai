"""Workspace members & roles, audit log and workspace settings (Spec §10 Settings, Audit Log)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field

from subpoena_schemas import (
    ApiKey,
    KeyKind,
    Member,
    Model,
    Role,
    Scope,
    WorkspaceSettings,
    utcnow,
)

from ..deps import Services, ServicesDep, audit, require
from ..problems import ProblemError

router = APIRouter(prefix="/v1", tags=["settings"])
AdminKey = Annotated[ApiKey, Depends(require(Scope.ADMIN))]
ReadKey = Annotated[ApiKey, Depends(require(Scope.EVALUATIONS_READ))]

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class AddMember(Model):
    email: str = Field(pattern=EMAIL, max_length=254)
    role: Role = Role.VIEWER
    name: str | None = Field(default=None, max_length=100)


class UpdateMember(Model):
    role: Role


class UpdateSettings(Model):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    pii_masking: bool | None = None


def _view(m: Member) -> dict[str, Any]:
    return m.model_dump(mode="json", exclude={"workspace_id"})


@router.get("/members")
async def list_members(key: AdminKey, services: ServicesDep) -> dict[str, Any]:
    members = await services.store.list_members(key.workspace_id)
    return {"data": [_view(m) for m in members]}


@router.post("/members", status_code=201)
async def add_member(body: AddMember, key: AdminKey, services: ServicesDep) -> dict[str, Any]:
    email = body.email.lower()
    if any(m.email == email for m in await services.store.list_members(key.workspace_id)):
        raise ProblemError(409, "member-exists", f"{email} is already a member")
    member = Member(
        workspace_id=key.workspace_id,
        email=email,
        name=body.name,
        role=body.role,
        added_by=key.name,
    )
    await services.store.put_member(member)
    await audit(services, key, "member.added", email, after={"role": member.role})
    return _view(member)


@router.patch("/members/{member_id}")
async def update_member(
    member_id: str, body: UpdateMember, key: AdminKey, services: ServicesDep
) -> dict[str, Any]:
    member = await _member(services, key.workspace_id, member_id)
    if member.role is Role.ADMIN and body.role is not Role.ADMIN:
        await _keep_an_admin(services, key.workspace_id, member)
    updated = member.model_copy(update={"role": body.role})
    await services.store.put_member(updated)
    await _revoke_sessions(services, key.workspace_id, member.id)  # new role on next sign-in
    await audit(
        services,
        key,
        "member.role_changed",
        member.email,
        before={"role": member.role},
        after={"role": body.role},
    )
    return _view(updated)


@router.delete("/members/{member_id}", status_code=204)
async def remove_member(member_id: str, key: AdminKey, services: ServicesDep) -> Response:
    member = await _member(services, key.workspace_id, member_id)
    if member.role is Role.ADMIN:
        await _keep_an_admin(services, key.workspace_id, member)
    await services.store.delete_member(key.workspace_id, member_id)
    await _revoke_sessions(services, key.workspace_id, member.id)
    await audit(services, key, "member.removed", member.email, before={"role": member.role})
    return Response(status_code=204)


@router.get("/audit-log")
async def audit_log(
    key: AdminKey,
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    action: str | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    rows = await services.store.list_audit(
        key.workspace_id, limit if not (action or actor) else 1000
    )
    if action:
        rows = [r for r in rows if r.action == action or r.action.startswith(f"{action}.")]
    if actor:
        rows = [r for r in rows if actor.lower() in r.actor.name.lower()]
    return {"data": [r.model_dump(mode="json") for r in rows[:limit]]}


@router.get("/settings")
async def get_settings_view(key: ReadKey, services: ServicesDep) -> dict[str, Any]:
    ws = await services.store.get_workspace(key.workspace_id)
    if ws is None:
        raise ProblemError(404, "not-found", "Workspace not found")
    return {
        "workspace": ws.model_dump(mode="json"),
        "sso": {"google": services.google_verifier is not None},
    }


@router.patch("/settings")
async def update_settings(
    body: UpdateSettings, key: AdminKey, services: ServicesDep
) -> dict[str, Any]:
    ws = await services.store.get_workspace(key.workspace_id)
    if ws is None:
        raise ProblemError(404, "not-found", "Workspace not found")
    changes = body.model_dump(exclude_none=True)
    settings = ws.settings.model_copy(
        update={k: v for k, v in changes.items() if k in WorkspaceSettings.model_fields}
    )
    updated = ws.model_copy(update={"name": changes.get("name", ws.name), "settings": settings})
    await services.store.put_workspace(updated)
    before = {"name": ws.name, **ws.settings.model_dump()}
    after = {"name": updated.name, **settings.model_dump()}
    await audit(
        services,
        key,
        "settings.updated",
        ws.id,
        before={k: v for k, v in before.items() if after[k] != v},
        after={k: v for k, v in after.items() if before[k] != v},
    )
    return {"workspace": updated.model_dump(mode="json")}


async def _member(services: Services, workspace_id: str, member_id: str) -> Member:
    member = await services.store.get_member(workspace_id, member_id)
    if member is None:
        raise ProblemError(404, "not-found", f"Member {member_id} not found")
    return member


async def _keep_an_admin(services: Services, workspace_id: str, leaving: Member) -> None:
    admins = [
        m
        for m in await services.store.list_members(workspace_id)
        if m.role is Role.ADMIN and m.id != leaving.id
    ]
    keys = [
        k
        for k in await services.store.list_api_keys(workspace_id)
        if k.kind is KeyKind.API_KEY and k.revoked_at is None and Scope.ADMIN in k.scopes
    ]
    if not admins and not keys:
        raise ProblemError(409, "last-admin", "A workspace needs at least one admin")


async def _revoke_sessions(services: Services, workspace_id: str, member_id: str) -> None:
    now = utcnow()
    for k in await services.store.list_api_keys(workspace_id):
        if k.kind is KeyKind.SESSION and k.member_id == member_id and k.revoked_at is None:
            await services.store.put_api_key(k.model_copy(update={"revoked_at": now}))

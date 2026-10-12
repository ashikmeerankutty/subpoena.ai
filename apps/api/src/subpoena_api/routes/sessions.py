"""Console sign-in with Google (Spec §10 Auth).

The Console runs the OAuth code flow and posts the Google ID token here. The API checks the
token (signature, audience, verified email, nonce), looks up the email's memberships and
issues a short-lived session credential whose scopes come from the member's role. Sessions
are ``ApiKey`` records of kind ``SESSION``, so every route authorizes them like keys.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from subpoena_schemas import (
    ROLE_SCOPES,
    Actor,
    ActorType,
    ApiKey,
    AuditEntry,
    KeyKind,
    Member,
    Model,
    utcnow,
)

from ..deps import Services, ServicesDep, authenticate
from ..problems import ProblemError
from ..security import display_prefix, hash_secret

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])
SESSION_TTL = timedelta(hours=12)


class GoogleSignIn(Model):
    id_token: str = Field(min_length=20, max_length=8192)
    nonce: str | None = Field(default=None, max_length=200)
    workspace_id: str | None = None


class SwitchWorkspace(Model):
    workspace_id: str


@router.post("/google", status_code=201)
async def sign_in_with_google(body: GoogleSignIn, services: ServicesDep) -> dict[str, Any]:
    if services.google_verifier is None:
        raise ProblemError(404, "sso-not-configured", "Google sign-in is not configured")
    try:
        claims = await services.google_verifier(body.id_token)
    except ValueError as exc:
        raise ProblemError(401, "invalid-id-token", f"Google ID token rejected: {exc}") from exc
    if not claims.get("email_verified") or not claims.get("email"):
        raise ProblemError(401, "unverified-email", "Google account email is not verified")
    if body.nonce is not None and claims.get("nonce") != body.nonce:
        raise ProblemError(401, "invalid-id-token", "Sign-in nonce does not match")
    email = str(claims["email"]).lower()
    memberships = await services.store.find_members_by_email(email)
    if not memberships:
        raise ProblemError(
            403,
            "not-a-member",
            f"{email} is not a member of any workspace; ask an admin to add you",
        )
    if body.workspace_id:
        member = next((m for m in memberships if m.workspace_id == body.workspace_id), None)
        if member is None:
            raise ProblemError(403, "not-a-member", f"{email} is not a member of that workspace")
    else:
        member = max(memberships, key=lambda m: (m.last_login_at is not None, m.last_login_at))
    if claims.get("name") and not member.name:
        member = member.model_copy(update={"name": str(claims["name"])})
    return await _issue(services, member, memberships)


@router.post("/switch", status_code=201)
async def switch_workspace(
    body: SwitchWorkspace,
    key: Annotated[ApiKey, Depends(authenticate)],
    services: ServicesDep,
) -> dict[str, Any]:
    current = await _session_member(services, key)
    memberships = await services.store.find_members_by_email(current.email)
    member = next((m for m in memberships if m.workspace_id == body.workspace_id), None)
    if member is None:
        raise ProblemError(403, "not-a-member", "You are not a member of that workspace")
    await services.store.put_api_key(key.model_copy(update={"revoked_at": utcnow()}))
    return await _issue(services, member, memberships)


@router.get("/current")
async def current(
    key: Annotated[ApiKey, Depends(authenticate)], services: ServicesDep
) -> dict[str, Any]:
    member = await _session_member(services, key)
    memberships = await services.store.find_members_by_email(member.email)
    return {
        "member": member.model_dump(mode="json"),
        "workspaces": await _workspaces(services, memberships),
    }


@router.delete("/current", status_code=204)
async def sign_out(
    key: Annotated[ApiKey, Depends(authenticate)], services: ServicesDep
) -> Response:
    if key.kind is KeyKind.SESSION:
        await services.store.put_api_key(key.model_copy(update={"revoked_at": utcnow()}))
    return Response(status_code=204)


async def _issue(services: Services, member: Member, memberships: list[Member]) -> dict[str, Any]:
    now = utcnow()
    secret = f"ss_{secrets.token_urlsafe(32)}"
    session = ApiKey(
        workspace_id=member.workspace_id,
        name=member.email,
        prefix=display_prefix(secret),
        hash=hash_secret(secret, services.settings.api_key_pepper.get_secret_value()),
        scopes=ROLE_SCOPES[member.role],
        created_by="google-sso",
        kind=KeyKind.SESSION,
        member_id=member.id,
        expires_at=now + SESSION_TTL,
    )
    await services.store.put_api_key(session)
    await services.store.put_member(member.model_copy(update={"last_login_at": now}))
    await services.store.append_audit(
        AuditEntry(
            workspace_id=member.workspace_id,
            actor=Actor(type=ActorType.MEMBER, id=member.id, name=member.email),
            action="member.signed_in",
            target=member.email,
            after={"method": "google", "role": member.role},
        )
    )
    ws = await services.store.get_workspace(member.workspace_id)
    return {
        "token": secret,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        "role": member.role,
        "workspace": {"id": member.workspace_id, "name": ws.name if ws else member.workspace_id},
        "workspaces": await _workspaces(services, memberships),
    }


async def _workspaces(services: Services, memberships: list[Member]) -> list[dict[str, Any]]:
    out = []
    for m in memberships:
        ws = await services.store.get_workspace(m.workspace_id)
        out.append(
            {"id": m.workspace_id, "name": ws.name if ws else m.workspace_id, "role": m.role}
        )
    return sorted(out, key=lambda w: str(w["name"]))


async def _session_member(services: Services, key: ApiKey) -> Member:
    if key.kind is not KeyKind.SESSION or key.member_id is None:
        raise ProblemError(400, "not-a-session", "This endpoint needs a Console sign-in session")
    member = await services.store.get_member(key.workspace_id, key.member_id)
    if member is None:
        raise ProblemError(401, "unauthenticated", "Membership no longer exists")
    return member

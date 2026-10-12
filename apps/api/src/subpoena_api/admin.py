"""Workspace bootstrap for deployed environments.

  uv run python -m subpoena_api.admin create-workspace "Acme Bank"
  uv run python -m subpoena_api.admin create-key ws_123 analyst --scopes evaluations:read evaluations:override
  uv run python -m subpoena_api.admin add-member ws_123 you@example.com --role ADMIN

Uses the same settings as the API (SUBPOENA_STORE=firestore, SUBPOENA_GCP_PROJECT and the
deployed SUBPOENA_API_KEY_PEPPER), so issued keys validate in the deployed service.
"""

from __future__ import annotations

import argparse
import asyncio

from subpoena_schemas import Actor, ActorType, AuditEntry, Member, Policy, Role, Scope, Workspace

from .main import build_services
from .routes.api_keys import issue_key
from .settings import get_settings


async def create_workspace(name: str) -> None:
    services = build_services(get_settings())
    ws = Workspace(name=name)
    await services.store.put_workspace(ws)
    await services.store.put_policy(Policy(workspace_id=ws.id))
    key = await issue_key(services, ws.id, "admin", [Scope.ADMIN], created_by="bootstrap")
    print(f"workspace_id={ws.id}\nadmin_key={key.secret}\n(the key is shown once)")


async def create_key(workspace_id: str, name: str, scopes: list[str]) -> None:
    services = build_services(get_settings())
    key = await issue_key(
        services, workspace_id, name, [Scope(s) for s in scopes], created_by="bootstrap"
    )
    print(f"key={key.secret}\n(shown once)")


async def add_member(workspace_id: str, email: str, role: str) -> None:
    services = build_services(get_settings())
    if await services.store.get_workspace(workspace_id) is None:
        raise SystemExit(f"unknown workspace {workspace_id}")
    existing = [
        m for m in await services.store.list_members(workspace_id) if m.email == email.lower()
    ]
    member = existing[0] if existing else Member(workspace_id=workspace_id, email=email.lower())
    member = member.model_copy(
        update={"role": Role(role), "added_by": member.added_by or "bootstrap"}
    )
    await services.store.put_member(member)
    await services.store.append_audit(
        AuditEntry(
            workspace_id=workspace_id,
            actor=Actor(type=ActorType.SYSTEM, name="admin CLI"),
            action="member.added" if not existing else "member.role_changed",
            target=member.email,
            after={"role": member.role},
        )
    )
    print(f"{member.email} is {member.role} in {workspace_id}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("create-workspace")
    w.add_argument("name")
    k = sub.add_parser("create-key")
    k.add_argument("workspace_id")
    k.add_argument("name")
    k.add_argument("--scopes", nargs="+", default=["evaluations:write", "evaluations:read"])
    m = sub.add_parser("add-member")
    m.add_argument("workspace_id")
    m.add_argument("email")
    m.add_argument("--role", choices=[r.value for r in Role], default="VIEWER")
    a = ap.parse_args()
    if a.cmd == "create-workspace":
        asyncio.run(create_workspace(a.name))
    elif a.cmd == "add-member":
        asyncio.run(add_member(a.workspace_id, a.email, a.role))
    else:
        asyncio.run(create_key(a.workspace_id, a.name, a.scopes))


if __name__ == "__main__":
    main()

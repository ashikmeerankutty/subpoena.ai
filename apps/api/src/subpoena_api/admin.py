"""Workspace bootstrap for deployed environments.

  uv run python -m subpoena_api.admin create-workspace "Acme Bank"
  uv run python -m subpoena_api.admin create-key ws_123 analyst --scopes evaluations:read evaluations:override

Uses the same settings as the API (SUBPOENA_STORE=firestore, SUBPOENA_GCP_PROJECT and the
deployed SUBPOENA_API_KEY_PEPPER), so issued keys validate in the deployed service.
"""

from __future__ import annotations

import argparse
import asyncio

from subpoena_schemas import Policy, Scope, Workspace

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


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("create-workspace")
    w.add_argument("name")
    k = sub.add_parser("create-key")
    k.add_argument("workspace_id")
    k.add_argument("name")
    k.add_argument("--scopes", nargs="+", default=["evaluations:write", "evaluations:read"])
    a = ap.parse_args()
    if a.cmd == "create-workspace":
        asyncio.run(create_workspace(a.name))
    else:
        asyncio.run(create_key(a.workspace_id, a.name, a.scopes))


if __name__ == "__main__":
    main()

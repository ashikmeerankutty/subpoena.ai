from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from subpoena_api.baselines import SeedBaselines
from subpoena_api.deps import Services
from subpoena_api.main import create_app
from subpoena_api.publisher import MemoryPublisher
from subpoena_api.routes.api_keys import issue_key
from subpoena_api.settings import Settings
from subpoena_api.webhooks import BankNotifier
from subpoena_schemas import Policy, Scope, Workspace
from subpoena_store import MemoryStore, Store

SETTINGS = Settings(env="test", publisher="memory", sync_wait_max_ms=0)
SCENARIOS: dict[str, dict[str, Any]] = {
    s["name"]: s for s in json.loads((SETTINGS.seed_dir / "scenarios.json").read_text())
}


@dataclass
class Env:
    client: TestClient
    services: Services
    publisher: MemoryPublisher
    workspace_id: str
    admin: str
    writer: str
    reader: str
    other_ws_admin: str

    def auth(self, secret: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {secret}"}


# SUBPOENA_TEST_STORE=firestore runs every API test against the Firestore emulator.
TEST_STORE = os.environ.get("SUBPOENA_TEST_STORE", "memory")


def make_store() -> Store:
    """Called inside the app's event loop: gRPC async channels bind to the loop they start in."""
    if TEST_STORE != "firestore":
        return MemoryStore()
    if "FIRESTORE_EMULATOR_HOST" not in os.environ:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set")
    from google.cloud import firestore

    from subpoena_store.firestore import FirestoreStore

    # A fresh project per test isolates data inside the shared emulator.
    return FirestoreStore(firestore.AsyncClient(project=f"test-{uuid.uuid4().hex[:12]}"))


def _env() -> Iterator[Env]:
    publisher = MemoryPublisher()
    services = Services(
        settings=SETTINGS,
        store=MemoryStore(),
        publisher=publisher,
        baselines=SeedBaselines(SETTINGS.seed_dir),
        notifier=BankNotifier(SETTINGS.webhook_signing_secret.get_secret_value()),
    )

    async def setup() -> tuple[str, str, str, str, str]:
        services.store = make_store()
        ws, other = Workspace(name="Acme Bank"), Workspace(name="Other Bank")
        for w in (ws, other):
            await services.store.put_workspace(w)
            await services.store.put_policy(Policy(workspace_id=w.id))
        admin = await issue_key(services, ws.id, "admin", [Scope.ADMIN], None)
        writer = await issue_key(
            services, ws.id, "backend", [Scope.EVALUATIONS_WRITE, Scope.EVALUATIONS_READ], None
        )
        reader = await issue_key(services, ws.id, "ro", [Scope.EVALUATIONS_READ], None)
        other_admin = await issue_key(services, other.id, "admin", [Scope.ADMIN], None)
        return ws.id, admin.secret, writer.secret, reader.secret, other_admin.secret

    with TestClient(create_app(services)) as client:
        ws_id, admin, writer, reader, other_admin = client.portal.call(setup)  # type: ignore[union-attr]
        yield Env(client, services, publisher, ws_id, admin, writer, reader, other_admin)


def scenario(name: str, **overrides: Any) -> dict[str, Any]:
    return SCENARIOS[name]["request"] | overrides

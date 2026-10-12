from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import FastAPI

from subpoena_schemas import ApiKey, Policy, Scope, Workspace
from subpoena_store import MemoryStore, Store, build_media_store

from . import problems
from .baselines import BaselineSource, FirestoreBaselines, SeedBaselines
from .deps import GoogleVerifier, Services
from .pii import MaskPiiMiddleware
from .publisher import LogPublisher, MemoryPublisher, Publisher, PubSubPublisher
from .routes import api_keys, console, destinations, evaluations, members, sessions, twilio
from .routes.api_keys import issue_key
from .security import display_prefix, hash_secret
from .settings import Settings, get_settings
from .webhooks import BankNotifier

log = logging.getLogger("subpoena_api")


def build_services(settings: Settings) -> Services:
    store: Store
    if settings.store == "firestore":
        from google.cloud import firestore

        from subpoena_store.firestore import FirestoreStore

        client = firestore.AsyncClient(
            project=settings.gcp_project, database=settings.firestore_database
        )
        store = FirestoreStore(client, timedelta(hours=settings.idempotency_ttl_hours))
    else:
        store = MemoryStore(timedelta(hours=settings.idempotency_ttl_hours))

    publisher: Publisher
    if settings.publisher == "pubsub":
        assert settings.gcp_project
        publisher = PubSubPublisher(settings.gcp_project, settings.pubsub_topic)
    elif settings.publisher == "memory":
        publisher = MemoryPublisher()
    else:
        publisher = LogPublisher()

    baselines: BaselineSource
    if settings.baselines == "firestore":
        assert settings.gcp_project
        baselines = FirestoreBaselines(settings.gcp_project, settings.firestore_database)
    else:
        baselines = SeedBaselines(settings.seed_dir)
    notifier = BankNotifier(
        settings.webhook_signing_secret.get_secret_value(),
        store=store,
        console_url=settings.console_public_url,
        project=settings.gcp_project,
    )
    return Services(
        settings=settings,
        store=store,
        publisher=publisher,
        baselines=baselines,
        notifier=notifier,
        google_verifier=google_verifier(settings.google_client_id)
        if settings.google_client_id
        else None,
        media=build_media_store(settings.media_store, settings.media_bucket, settings.gcp_project),
    )


def google_verifier(client_id: str) -> GoogleVerifier:
    """Checks signature (Google's published keys), issuer, expiry and audience."""
    import asyncio

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    transport = google_requests.Request()

    async def verify(token: str) -> dict[str, Any]:
        claims: dict[str, Any] = await asyncio.to_thread(
            id_token.verify_oauth2_token, token, transport, client_id
        )
        return claims

    return verify


def create_app(services: Services | None = None, *, bootstrap_local: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if bootstrap_local:
            await _bootstrap_local(app.state.services)
        yield

    app = FastAPI(
        title="Subpoena.ai API",
        version="0.1.0",
        description="Multi-agent fraud defense engine that calls the user as a witness.",
        lifespan=lifespan,
    )
    app.state.services = services or build_services(get_settings())
    problems.install(app)
    app.add_middleware(MaskPiiMiddleware)
    app.include_router(evaluations.router)
    app.include_router(api_keys.router)
    app.include_router(console.router)
    app.include_router(members.router)
    app.include_router(destinations.router)
    app.include_router(sessions.router)
    app.include_router(twilio.router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _bootstrap_local(services: Services) -> None:
    """For in-memory runs: create a workspace and an admin key.

    ``SUBPOENA_LOCAL_ADMIN_KEY`` pins the key's secret (handy for the Console in development).
    """
    ws = Workspace(name="Acme Bank")
    await services.store.put_workspace(ws)
    await services.store.put_policy(Policy(workspace_id=ws.id))
    fixed = os.environ.get("SUBPOENA_LOCAL_ADMIN_KEY")
    if fixed:
        pepper = services.settings.api_key_pepper.get_secret_value()
        await services.store.put_api_key(
            ApiKey(
                workspace_id=ws.id,
                name="local-admin",
                prefix=display_prefix(fixed),
                hash=hash_secret(fixed, pepper),
                scopes=[Scope.ADMIN],
            )
        )
        log.warning("Local admin API key: %s… (from SUBPOENA_LOCAL_ADMIN_KEY)", fixed[:12])
        return
    created = await issue_key(services, ws.id, "local-admin", [Scope.ADMIN], created_by=None)
    log.warning("Local admin API key (shown once): %s", created.secret)


def local_app() -> FastAPI:
    """Uvicorn factory for local development: ``uvicorn subpoena_api.main:local_app --factory``."""
    logging.basicConfig(level=logging.INFO)
    return create_app(bootstrap_local=True)

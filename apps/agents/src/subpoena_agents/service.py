"""Courtroom worker for Cloud Run.

  POST /pubsub/push            Pub/Sub push: evaluations.created | subpoena.activity
  POST /tasks/subpoena-timeout Cloud Tasks: subpoena expiry

The service is private (Cloud Run IAM); Pub/Sub and Cloud Tasks call it with OIDC tokens.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from fastapi import FastAPI, Request, Response

from subpoena_store import MemoryStore, Store

from .config import CourtSettings
from .scheduler import CloudTasksScheduler, Scheduler
from .wiring import build_courtroom

log = logging.getLogger(__name__)


def _store(s: CourtSettings) -> Store:
    if s.store != "firestore":
        return MemoryStore()
    from google.cloud import firestore

    from subpoena_store.firestore import FirestoreStore

    return FirestoreStore(
        firestore.AsyncClient(project=s.gcp_project, database=s.firestore_database)
    )


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    for noisy in ("httpx", "google_adk", "google_genai", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    import os

    court_settings = CourtSettings()
    scheduler: Scheduler | None = None
    if os.environ.get("SUBPOENA_TASKS_QUEUE"):
        scheduler = CloudTasksScheduler(
            project=os.environ["SUBPOENA_GCP_PROJECT"],
            location=os.environ.get("SUBPOENA_TASKS_LOCATION", "us-central1"),
            queue=os.environ["SUBPOENA_TASKS_QUEUE"],
            target_url=os.environ["SUBPOENA_COURTROOM_URL"].rstrip("/") + "/tasks/subpoena-timeout",
            service_account=os.environ["SUBPOENA_TASKS_SERVICE_ACCOUNT"],
        )
    store = _store(court_settings)
    court = build_courtroom(court_settings, store, scheduler=scheduler)
    app = FastAPI(title="Subpoena.ai courtroom", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/pubsub/push")
    async def push(request: Request) -> Response:
        envelope: dict[str, Any] = await request.json()
        message = envelope.get("message") or {}
        data = json.loads(base64.b64decode(message.get("data", "")) or b"{}")
        kind = (message.get("attributes") or {}).get("kind", "evaluation.created")
        if kind == "subpoena.activity":
            await court.handle_inbound(data["subpoena_id"])
        else:
            await court.run_case(data["evaluation_id"])
        return Response(status_code=204)

    @app.post("/tasks/subpoena-timeout")
    async def timeout(request: Request) -> Response:
        body = await request.json()
        await court.handle_timeout(body["subpoena_id"])
        return Response(status_code=204)

    return app

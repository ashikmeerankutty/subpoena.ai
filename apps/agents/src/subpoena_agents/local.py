"""Everything in one process for development and offline demos:
REST API + courtroom + MCP server (in-process) sharing one store.

  SUBPOENA_LLM=gemini SUBPOENA_GCP_PROJECT=subpoena-ai \\
  uv run uvicorn subpoena_agents.local:app --factory --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from fastapi import FastAPI

from subpoena_api.main import build_services, create_app
from subpoena_api.settings import Settings, get_settings
from subpoena_schemas import Evaluation

from .config import CourtSettings
from .courtroom import Courtroom
from .wiring import build_courtroom

log = logging.getLogger(__name__)


class InlinePublisher:
    """Runs courtroom work as background tasks instead of going through Pub/Sub."""

    def __init__(self, court: Courtroom) -> None:
        self._court = court
        self._tasks: set[asyncio.Task[Any]] = set()

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("courtroom task failed", exc_info=task.exception())

    async def publish_evaluation_created(self, ev: Evaluation) -> None:
        self._spawn(self._court.run_case(ev.evaluation_id))

    async def publish_subpoena_activity(self, subpoena_id: str) -> None:
        self._spawn(self._court.handle_inbound(subpoena_id))


def build_local_app(
    settings: Settings, court_settings: CourtSettings, *, bootstrap: bool
) -> FastAPI:
    services = build_services(settings)
    court = build_courtroom(
        court_settings, services.store, notifier=services.notifier, media=services.media
    )
    services.publisher = InlinePublisher(court)
    application = create_app(services, bootstrap_local=bootstrap)
    application.state.courtroom = court
    return application


def app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    for noisy in ("httpx", "google_adk", "google_genai", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = get_settings()
    return build_local_app(settings, CourtSettings(), bootstrap=settings.store == "memory")

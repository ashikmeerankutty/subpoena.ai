"""Assemble a Courtroom from settings (shared by the worker service, the local stack and tests)."""

from __future__ import annotations

from subpoena_api.webhooks import BankNotifier
from subpoena_mcp.app import build_deps
from subpoena_mcp.client import McpConnector
from subpoena_mcp.config import McpSettings
from subpoena_mcp.server import ALLOW_LIST, build_server
from subpoena_store import Store

from .config import CourtSettings
from .courtroom import Courtroom
from .llm import GeminiLlm, Llm, ScriptedLlm
from .scheduler import LocalScheduler, Scheduler
from .screening import HeuristicScreener, ModelArmorScreener, Screener


def build_courtroom(
    settings: CourtSettings,
    store: Store,
    *,
    mcp_settings: McpSettings | None = None,
    scheduler: Scheduler | None = None,
    llm: Llm | None = None,
    notifier: BankNotifier | None = None,
) -> Courtroom:
    if settings.mcp == "http":
        assert settings.mcp_url, "SUBPOENA_MCP_URL is required when SUBPOENA_MCP=http"
        mcp = McpConnector(
            base_url=settings.mcp_url,
            token_secret=settings.agent_token_secret.get_secret_value(),
            id_token_audience=settings.mcp_audience,
        )
    else:
        deps = build_deps(mcp_settings or McpSettings(), store)
        mcp = McpConnector(servers={a: build_server(a, deps) for a in ALLOW_LIST})

    screener: Screener = HeuristicScreener()
    if settings.screening == "model_armor" and settings.model_armor_template:
        screener = ModelArmorScreener(settings.model_armor_template, settings.model_armor_location)

    local = scheduler is None
    court = Courtroom(
        store=store,
        mcp=mcp,
        llm=llm or (GeminiLlm(settings) if settings.llm == "gemini" else ScriptedLlm()),
        screener=screener,
        notifier=notifier or BankNotifier(settings.webhook_signing_secret.get_secret_value()),
        scheduler=scheduler or LocalScheduler(),
        max_rounds=settings.max_rounds,
    )
    if local and isinstance(court.scheduler, LocalScheduler):
        court.scheduler.on_timeout = court.handle_timeout
    return court

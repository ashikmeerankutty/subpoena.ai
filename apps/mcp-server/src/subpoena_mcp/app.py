"""HTTP deployment: one Streamable-HTTP MCP endpoint per agent at ``/{agent}/mcp``.

Each request must carry ``X-Agent-Token: HMAC(secret, agent)``, so an agent can only reach
its own endpoint (and therefore only its own allow-listed tools). On Cloud Run the service
is additionally private: callers need an IAM identity token in ``Authorization``.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from subpoena_schemas import Agent
from subpoena_store import MemoryStore, Store

from .config import McpSettings
from .data import BigQueryData, DataSource, SeedData
from .server import McpDeps, build_server
from .witness import SimulatorChannel, TwilioChannel, WitnessChannel

TOKEN_HEADER = "x-agent-token"


def agent_token(secret: str, agent: Agent) -> str:
    return hmac.new(secret.encode(), agent.value.encode(), hashlib.sha256).hexdigest()


def build_deps(settings: McpSettings, store: Store | None = None) -> McpDeps:
    if store is None:
        if settings.store == "firestore":
            from google.cloud import firestore

            from subpoena_store.firestore import FirestoreStore

            store = FirestoreStore(
                firestore.AsyncClient(
                    project=settings.gcp_project, database=settings.firestore_database
                )
            )
        else:
            store = MemoryStore()
    data: DataSource
    if settings.data == "bigquery":
        assert settings.gcp_project, "SUBPOENA_GCP_PROJECT required for BigQuery data"
        data = BigQueryData(settings.seed_dir, settings.gcp_project, settings.bq_dataset)
    else:
        data = SeedData(settings.seed_dir)
    witness: WitnessChannel = (
        TwilioChannel(store, settings)
        if settings.witness_channel == "twilio"
        else SimulatorChannel(store, data)
    )
    return McpDeps(
        data=data,
        store=store,
        witness=witness,
        sim_swap_window=timedelta(days=settings.sim_swap_window_days),
    )


class _AgentAuth:
    def __init__(self, app: ASGIApp, expected: str) -> None:
        self._app = app
        self._expected = expected

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if not hmac.compare_digest(headers.get(TOKEN_HEADER, ""), self._expected):
                await JSONResponse({"error": "invalid agent token"}, status_code=403)(
                    scope, receive, send
                )
                return
        await self._app(scope, receive, send)


def create_app(settings: McpSettings | None = None, deps: McpDeps | None = None) -> Starlette:
    settings = settings or McpSettings()
    deps = deps or build_deps(settings)
    secret = settings.agent_token_secret.get_secret_value()
    servers = {agent: build_server(agent, deps) for agent in Agent if agent in _SERVED}
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

    routes: list[Route | Mount] = [Route("/healthz", _health)]
    for agent, server in servers.items():
        asgi = server.streamable_http_app(
            streamable_http_path="/mcp", stateless_http=True, transport_security=security
        )
        routes.append(Mount(f"/{agent.value}", app=_AgentAuth(asgi, agent_token(secret, agent))))

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for server in servers.values():
                await stack.enter_async_context(server.session_manager.run())
            yield

    return Starlette(routes=routes, lifespan=lifespan)


_SERVED = {
    Agent.CLERK,
    Agent.GEO,
    Agent.DEVICE,
    Agent.VELOCITY,
    Agent.MERCHANT,
    Agent.GRAPH,
    Agent.PROSECUTOR,
    Agent.DEFENSE,
    Agent.JUDGE,
    Agent.BAILIFF,
}


def _health(_: Request) -> Response:
    return Response("ok")

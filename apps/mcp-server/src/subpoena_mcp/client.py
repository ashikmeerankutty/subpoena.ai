"""How agents talk to the MCP server: in-process (tests, local stack) or over HTTP."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp.shared._httpx_utils import create_mcp_http_client

from subpoena_schemas import Agent

from .app import TOKEN_HEADER, agent_token


class ToolError(RuntimeError):
    pass


class AgentSession:
    """An agent's view of the MCP server: only what its endpoint exposes."""

    def __init__(self, agent: Agent, client: Client) -> None:
        self.agent = agent
        self._client = client

    async def tool_names(self) -> list[str]:
        return [t.name for t in (await self._client.list_tools()).tools]

    async def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        result = await self._client.call_tool(name, arguments)
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            raise ToolError(f"{self.agent.value} -> {name}: {text}")
        if result.structured_content is not None:
            data = result.structured_content
            # Non-object returns are wrapped as {"result": ...}
            return data if "result" not in data or len(data) > 1 else {"result": data["result"]}
        text = "".join(getattr(c, "text", "") for c in result.content)
        parsed: dict[str, Any] = json.loads(text)
        return parsed

    async def read(self, uri: str) -> dict[str, Any]:
        result = await self._client.read_resource(uri)
        text = "".join(getattr(c, "text", "") for c in result.contents)
        parsed: dict[str, Any] = json.loads(text)
        return parsed


class McpConnector:
    """Opens per-agent sessions against either in-process servers or the HTTP deployment."""

    def __init__(
        self,
        *,
        servers: dict[Agent, MCPServer] | None = None,
        base_url: str | None = None,
        token_secret: str | None = None,
        id_token_audience: str | None = None,
    ) -> None:
        if (servers is None) == (base_url is None):
            raise ValueError("pass exactly one of servers or base_url")
        self._servers = servers
        self._base_url = base_url.rstrip("/") if base_url else None
        self._secret = token_secret
        self._audience = id_token_audience

    @asynccontextmanager
    async def session(self, agent: Agent) -> AsyncIterator[AgentSession]:
        try:
            async with self._open(agent) as session:
                yield session
        except BaseExceptionGroup as group:
            # The SDK's task groups wrap errors; surface the single real cause.
            leaf: BaseException = group
            while isinstance(leaf, BaseExceptionGroup) and len(leaf.exceptions) == 1:
                leaf = leaf.exceptions[0]
            raise leaf from None

    @asynccontextmanager
    async def _open(self, agent: Agent) -> AsyncIterator[AgentSession]:
        if self._servers is not None:
            async with Client(self._servers[agent]) as client:
                yield AgentSession(agent, client)
            return
        assert self._secret is not None
        headers = {TOKEN_HEADER: agent_token(self._secret, agent)}
        if self._audience:
            headers["Authorization"] = f"Bearer {_id_token(self._audience)}"
        http = create_mcp_http_client(headers=headers)
        transport = streamable_http_client(f"{self._base_url}/{agent.value}/mcp", http_client=http)
        async with http, Client(transport) as client:
            yield AgentSession(agent, client)


def _id_token(audience: str) -> str:
    import google.auth.transport.requests
    from google.oauth2 import id_token

    request = google.auth.transport.requests.Request()
    token: str = id_token.fetch_id_token(request, audience)  # type: ignore[no-untyped-call]
    return token

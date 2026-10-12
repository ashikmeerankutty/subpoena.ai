from __future__ import annotations

from starlette.testclient import TestClient

from subpoena_mcp.app import TOKEN_HEADER, agent_token, create_app
from subpoena_mcp.config import McpSettings
from subpoena_schemas import Agent

SETTINGS = McpSettings()
SECRET = SETTINGS.agent_token_secret.get_secret_value()
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_wrong_or_other_agent_token_is_rejected() -> None:
    with TestClient(create_app(SETTINGS)) as c:
        assert c.get("/healthz").text == "ok"
        r = c.post("/judge/mcp", json=INIT, headers=HEADERS)
        assert r.status_code == 403
        # A prosecutor token does not open the judge's endpoint.
        r = c.post(
            "/judge/mcp",
            json=INIT,
            headers=HEADERS | {TOKEN_HEADER: agent_token(SECRET, Agent.PROSECUTOR)},
        )
        assert r.status_code == 403


def test_correct_token_reaches_server() -> None:
    with TestClient(create_app(SETTINGS)) as c:
        r = c.post(
            "/judge/mcp",
            json=INIT,
            headers=HEADERS | {TOKEN_HEADER: agent_token(SECRET, Agent.JUDGE)},
        )
        assert r.status_code == 200, r.text

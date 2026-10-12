from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from subpoena_mcp.app import build_deps
from subpoena_mcp.client import McpConnector, ToolError
from subpoena_mcp.config import McpSettings
from subpoena_mcp.server import ALLOW_LIST, BAILIFF_TOOLS, READ_TOOLS, build_server
from subpoena_schemas import Agent, Evaluation, EvaluationRequest, MessageDirection, Workspace
from subpoena_store import MemoryStore

SETTINGS = McpSettings()
SCENARIOS = {s["name"]: s for s in json.loads((SETTINGS.seed_dir / "scenarios.json").read_text())}


@pytest.fixture
def stack() -> tuple[McpConnector, MemoryStore]:
    store = MemoryStore()
    deps = build_deps(SETTINGS, store)
    servers = {a: build_server(a, deps) for a in Agent if a in ALLOW_LIST}
    return McpConnector(servers=servers), store


def run(fn: Callable[[], Awaitable[Any]]) -> Any:
    return asyncio.run(fn())


@pytest.mark.parametrize(
    ("agent", "expected"),
    [
        (Agent.GEO, READ_TOOLS),
        (Agent.PROSECUTOR, set()),
        (Agent.JUDGE, {"issue_subpoena"}),
        (Agent.BAILIFF, BAILIFF_TOOLS),
    ],
)
def test_each_agent_sees_only_its_tools(stack, agent: Agent, expected: set[str]) -> None:
    conn, _ = stack

    async def go() -> set[str]:
        async with conn.session(agent) as s:
            return set(await s.tool_names())

    assert run(go) == expected


def test_disallowed_tool_cannot_be_called(stack) -> None:
    conn, _ = stack

    async def go() -> None:
        async with conn.session(Agent.PROSECUTOR) as s:
            await s.call("lookup_phone", user_id="usr_9921")

    with pytest.raises(ToolError):
        run(go)


def test_bailiff_has_no_resources(stack) -> None:
    conn, _ = stack

    async def go() -> None:
        async with conn.session(Agent.BAILIFF) as s:
            await s.read("user_profile://usr_9921/baselines")

    with pytest.raises(Exception, match=r"(?i)resource"):
        run(go)


def test_resources(stack) -> None:
    conn, _ = stack

    async def go() -> tuple[dict[str, Any], ...]:
        async with conn.session(Agent.CLERK) as s:
            return (
                await s.read("user_profile://usr_9921/baselines"),
                await s.read("transactions://usr_9921/recent"),
                await s.read("graph://198.51.100.66/neighbors"),
                await s.read("precedents://search/auto parts new device night"),
                await s.read("policy://ws_x/active"),
            )

    baseline, recent, graph, precedents, policy = run(go)
    assert baseline["known_devices"] == ["dev-alex-iphone15", "dev-alex-macbook"]
    assert len(recent["transactions"]) == 50
    assert recent["transactions"][0]["occurred_at"] > recent["transactions"][-1]["occurred_at"]
    assert graph["flag"] == "MULE_LINKED" and {n["flag"] for n in graph["neighbors"]} == {"MULE"}
    assert precedents["precedents"][0]["id"] == "P1"
    assert policy["thresholds"] == {"approve_max": 0.15, "block_min": 0.85}


def test_read_tools(stack) -> None:
    conn, _ = stack

    async def go() -> tuple[dict[str, Any], ...]:
        async with conn.session(Agent.GEO) as s:
            return (
                await s.call(
                    "geo_velocity",
                    user_id="usr_9921",
                    ip_address="203.0.113.44",
                    timestamp="2026-10-09T09:14:03Z",
                ),
                await s.call(
                    "geo_velocity",
                    user_id="usr_3003",
                    ip_address="198.51.100.66",
                    timestamp="2026-10-09T08:03:55Z",
                ),
                await s.call("query_asn_reputation", ip_address="198.51.100.66"),
                await s.call("validate_merchant", merchant_name="QuickCash Transfers", mcc="4829"),
                await s.call("validate_merchant", merchant_name="autozone online", mcc="5533"),
            )

    alex, jordan, asn, quickcash, autozone = run(go)
    assert alex["ip_city"] == "Oakland" and not alex["impossible_travel"]
    assert jordan["ip_country"] == "NG" and jordan["distance_from_home_km"] > 9000
    assert asn["risk"] == "HIGH" and asn["is_vpn_or_proxy"]
    assert quickcash["risk"] == "HIGH" and quickcash["status"] == "UNVERIFIED"
    assert autozone["risk"] == "LOW" and autozone["mcc_matches"]


def test_bailiff_lookup_and_codes(stack) -> None:
    conn, store = stack

    async def go() -> dict[str, Any]:
        async with conn.session(Agent.BAILIFF) as s:
            sam = await s.call("lookup_phone", user_id="usr_2002")
            alex = await s.call("lookup_phone", user_id="usr_9921")
            assert sam["recent_sim_swap"] and not alex["recent_sim_swap"]
            await s.call(
                "send_verification",
                user_id="usr_9921",
                phone="+14155550123",
                evaluation_id="eval_1",
                subpoena_id="sbp_1",
            )
            msgs = await store.list_messages("+14155550123")
            code = msgs[-1].body.split("code is ")[1][:6]
            wrong = await s.call(
                "check_verification",
                phone="+14155550123",
                code="000000" if code != "000000" else "111111",
            )
            ok = await s.call("check_verification", phone="+14155550123", code=code)
            again = await s.call("check_verification", phone="+14155550123", code=code)
            return {"wrong": wrong, "ok": ok, "again": again}

    r = run(go)
    assert r["wrong"]["status"] == "pending"
    assert r["ok"]["status"] == "approved"
    assert r["again"]["status"] == "expired"  # codes are single-use


def test_issue_subpoena_writes_witness_conversation(stack) -> None:
    conn, store = stack
    req = EvaluationRequest.model_validate(SCENARIOS["auto_parts_deadlock"]["request"])

    async def go() -> dict[str, Any]:
        ws = Workspace(name="Acme Bank")
        await store.put_workspace(ws)
        ev = Evaluation(
            workspace_id=ws.id, transaction=req.transaction(), witness=req.witness, policy_version=1
        )
        await store.put_evaluation(ev)
        async with conn.session(Agent.JUDGE) as s:
            return await s.call(
                "issue_subpoena",
                evaluation_id=ev.evaluation_id,
                subpoena_id="sbp_1",
                question="Are you working on a car?",
                channels=["VOICE", "WHATSAPP", "SMS"],
            )

    result = run(go)
    assert result["sent"] and result["channel"] == "WHATSAPP"
    assert "Hi Alex, this is Acme Bank Security" in result["body"]
    assert "$4,500.00" in result["body"]
    msgs = run(lambda: store.list_messages("+14155550123"))
    assert [m.direction for m in msgs] == [MessageDirection.OUTBOUND]

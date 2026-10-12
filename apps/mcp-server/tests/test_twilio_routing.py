from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from subpoena_mcp.app import build_deps
from subpoena_mcp.client import McpConnector
from subpoena_mcp.config import McpSettings
from subpoena_mcp.server import ALLOW_LIST, build_server
from subpoena_mcp.witness import RoutedChannel, TwilioChannel, TwilioError
from subpoena_schemas import Agent, Channel
from subpoena_store import MemoryStore

LIVE = "+919990000001"
SEEDED = "+14155550123"


def twilio_settings(**kw: Any) -> McpSettings:
    return McpSettings(
        witness_channel="twilio",
        twilio_account_sid="ACtest",
        twilio_auth_token=SecretStr("token"),
        twilio_whatsapp_from="whatsapp:+14155238886",
        twilio_verify_service_sid="VAtest",
        twilio_live_numbers=f" {LIVE} ,",
        **kw,
    )


def fake_twilio(channel: TwilioChannel, lookup: dict[str, Any] | int) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.host == "lookups.twilio.com":
            if isinstance(lookup, int):
                return httpx.Response(lookup, json={"code": 60600})
            return httpx.Response(200, json=lookup)
        return httpx.Response(201, json={"sid": "SMlive", "status": "pending"})

    channel._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return seen


def stack(
    settings: McpSettings, lookup: dict[str, Any] | int
) -> tuple[McpConnector, list[httpx.Request]]:
    deps = build_deps(settings, MemoryStore())
    assert isinstance(deps.witness, RoutedChannel)
    seen = fake_twilio(deps.witness._twilio, lookup)  # type: ignore[arg-type]
    servers = {a: build_server(a, deps) for a in Agent if a in ALLOW_LIST}
    return McpConnector(servers=servers), seen


def test_live_numbers_use_twilio_and_seeded_numbers_stay_simulated() -> None:
    conn, seen = stack(
        twilio_settings(), {"sim_swap": {"last_sim_swap": {"swapped_period": "PT2000H"}}}
    )

    async def go() -> tuple[dict[str, Any], dict[str, Any]]:
        async with conn.session(Agent.BAILIFF) as s:
            live = await s.call("lookup_phone", user_id="usr_x", phone=LIVE)
            seeded = await s.call("lookup_phone", user_id="usr_9921", phone=SEEDED)
            await s.call(
                "send_verification", user_id="u", phone=LIVE, evaluation_id="e", subpoena_id="s"
            )
            await s.call(
                "send_verification", user_id="u", phone=SEEDED, evaluation_id="e", subpoena_id="s"
            )
        return live, seeded

    live, seeded = asyncio.run(go())
    assert live["source"] == "twilio" and live["sim_swap_checked"] and not live["recent_sim_swap"]
    assert seeded["source"] == "simulator"
    assert [r.url.host for r in seen] == ["lookups.twilio.com", "verify.twilio.com"]


@pytest.mark.parametrize(
    "lookup", [403, {"sim_swap": {"error_code": 60606}}, {"line_type_intelligence": {}}]
)
@pytest.mark.parametrize("required", [True, False])
def test_unknown_sim_swap_status_fails_closed_unless_disabled(lookup: Any, required: bool) -> None:
    conn, _ = stack(twilio_settings(sim_swap_required=required), lookup)

    async def go() -> dict[str, Any]:
        async with conn.session(Agent.BAILIFF) as s:
            return await s.call("lookup_phone", user_id="usr_x", phone=LIVE)

    r = asyncio.run(go())
    assert r["sim_swap_checked"] is False
    assert r["recent_sim_swap"] is required


def test_whatsapp_message_goes_through_the_sandbox_sender() -> None:
    settings = twilio_settings(
        twilio_status_callback_url="https://api.example/v1/webhooks/twilio/status"
    )
    channel = TwilioChannel(MemoryStore(), settings)
    seen = fake_twilio(channel, {})
    msg = asyncio.run(channel.send_message(LIVE, "hello", Channel.WHATSAPP, context={}))
    form = dict(httpx.QueryParams(seen[0].content.decode()))
    assert form["To"] == f"whatsapp:{LIVE}" and form["From"] == "whatsapp:+14155238886"
    assert form["StatusCallback"].endswith("/twilio/status")
    assert msg.sid == "SMlive"


def test_twilio_errors_carry_the_twilio_code_and_message() -> None:
    channel = TwilioChannel(MemoryStore(), twilio_settings())
    channel._http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(400, json={"code": 21654, "message": "ContentSid Required"})
        )
    )
    with pytest.raises(TwilioError, match=r"21654.*ContentSid Required"):
        asyncio.run(channel.send_message(LIVE, "hello", Channel.WHATSAPP, context={}))


@pytest.mark.parametrize("fallback", [True, False])
def test_rejected_message_falls_back_to_the_simulator_when_enabled(fallback: bool) -> None:
    store = MemoryStore()
    deps = build_deps(twilio_settings(twilio_message_fallback=fallback), store)
    assert isinstance(deps.witness, RoutedChannel)
    deps.witness._twilio._http = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(
            lambda req: (
                httpx.Response(400, json={"code": 63007, "message": "no channel"})
                if req.url.host == "api.twilio.com"
                else httpx.Response(201, json={"status": "pending"})
            )
        )
    )

    async def go() -> dict[str, Any]:
        async with McpConnector(
            servers={a: build_server(a, deps) for a in Agent if a in ALLOW_LIST}
        ).session(Agent.BAILIFF) as s:
            code = await s.call(
                "send_verification", user_id="u", phone=LIVE, evaluation_id="e", subpoena_id="s"
            )
            return {"code": code, "messages": await store.list_messages(LIVE)}

    r = asyncio.run(go())
    assert r["code"]["status"] == "pending"  # codes still go through Twilio Verify
    assert r["messages"] == []
    witness = deps.witness
    if fallback:
        msg = asyncio.run(witness.send_message(LIVE, "question", Channel.WHATSAPP, context={}))
        assert msg.body == "question"
        assert [m.body for m in asyncio.run(store.list_messages(LIVE))] == ["question"]
    else:
        with pytest.raises(TwilioError, match="63007"):
            asyncio.run(witness.send_message(LIVE, "question", Channel.WHATSAPP, context={}))

"""MCP resources and tools (Spec §7) with a per-agent allow-list enforced by construction.

``build_server(agent, deps)`` registers only the resources and tools that agent may use, so a
disallowed tool is not merely refused: it does not exist on that agent's endpoint and never
appears in its tool list. Prompts cannot widen access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from mcp.server.mcpserver import MCPServer

from subpoena_schemas import Agent, Channel, Policy, utcnow
from subpoena_store import Store

from . import intel
from .data import DataSource
from .witness import WitnessChannel

RESOURCES = "resources"

READ_TOOLS = {"query_asn_reputation", "geo_velocity", "validate_merchant"}
BAILIFF_TOOLS = {"lookup_phone", "send_verification", "check_verification", "message_witness"}

ALLOW_LIST: dict[Agent, set[str]] = {
    Agent.CLERK: {RESOURCES},
    Agent.GEO: {RESOURCES, *READ_TOOLS},
    Agent.DEVICE: {RESOURCES, *READ_TOOLS},
    Agent.VELOCITY: {RESOURCES, *READ_TOOLS},
    Agent.MERCHANT: {RESOURCES, *READ_TOOLS},
    Agent.GRAPH: {RESOURCES, *READ_TOOLS},
    Agent.PROSECUTOR: {RESOURCES},
    Agent.DEFENSE: {RESOURCES},
    Agent.JUDGE: {RESOURCES, "issue_subpoena"},
    Agent.BAILIFF: BAILIFF_TOOLS,
    Agent.STENOGRAPHER: set(),
}


@dataclass
class McpDeps:
    data: DataSource
    store: Store
    witness: WitnessChannel
    sim_swap_window: timedelta = timedelta(days=7)
    sim_swap_required: bool = True


def _money(amount: Any) -> str:
    return f"${Decimal(str(amount)):,.2f}"


def build_server(agent: Agent, deps: McpDeps) -> MCPServer:
    allowed = ALLOW_LIST[agent]
    server = MCPServer(
        name=f"subpoena-{agent.value}",
        instructions=f"Subpoena.ai bank-data access for the {agent.value} agent. Read-only "
        "unless a tool says otherwise.",
    )

    def tool(fn: Any) -> Any:
        return server.tool()(fn) if fn.__name__ in allowed else fn

    if RESOURCES in allowed:
        _register_resources(server, deps)

    @tool
    def query_asn_reputation(ip_address: str) -> dict[str, Any]:
        """VPN / proxy / hosting ASN check for an IP address."""
        return intel.asn_reputation(deps.data, ip_address)

    @tool
    def geo_velocity(user_id: str, ip_address: str, timestamp: str) -> dict[str, Any]:
        """Impossible-travel check: distance and implied speed from the user's last location."""
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return intel.geo_velocity(deps.data, user_id, ip_address, ts)

    @tool
    def validate_merchant(merchant_name: str, mcc: str) -> dict[str, Any]:
        """Merchant existence, registration status and category check."""
        return intel.validate_merchant(deps.data, merchant_name, mcc)

    @tool
    async def lookup_phone(user_id: str, phone: str | None = None) -> dict[str, Any]:
        """Line type and SIM-swap recency for the user's registered phone (Bailiff only)."""
        phone = phone or (deps.data.user(user_id) or {}).get("phone")
        if not phone:
            return {"found": False}
        result = await deps.witness.lookup(phone)
        last = result.get("last_sim_swap")
        recent = False
        if last:
            swapped = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            recent = utcnow() - swapped < deps.sim_swap_window
        checked = bool(result.get("sim_swap_checked", True))
        if not checked and deps.sim_swap_required:
            recent = True  # fail closed: an unknown SIM-swap status is treated as a swap
        return {
            "found": True,
            **result,
            "sim_swap_checked": checked,
            "recent_sim_swap": recent,
            "window_days": deps.sim_swap_window.days,
        }

    @tool
    async def send_verification(
        user_id: str, phone: str, evaluation_id: str, subpoena_id: str
    ) -> dict[str, Any]:
        """Send a one-time code to the witness (Bailiff only)."""
        ctx = {"evaluation_id": evaluation_id, "subpoena_id": subpoena_id}
        return await deps.witness.send_code(phone, context=ctx)

    @tool
    async def check_verification(phone: str, code: str) -> dict[str, Any]:
        """Check a one-time code the witness sent back (Bailiff only)."""
        return await deps.witness.check_code(phone, code)

    @tool
    async def message_witness(subpoena_id: str, body: str) -> dict[str, Any]:
        """Send a follow-up to the witness of an existing subpoena, on its channel (Bailiff only).
        Only numbers that already received a subpoena can be messaged."""
        sub = await deps.store.get_subpoena(subpoena_id)
        if sub is None:
            return {"sent": False, "reason": "unknown subpoena"}
        ctx = {
            "workspace_id": sub.workspace_id,
            "evaluation_id": sub.evaluation_id,
            "subpoena_id": sub.id,
        }
        msg = await deps.witness.send_message(sub.phone, body[:500], sub.channel, context=ctx)
        return {"sent": True, "sid": msg.sid}

    @tool
    async def issue_subpoena(
        evaluation_id: str,
        subpoena_id: str,
        question: str,
        channels: list[str],
    ) -> dict[str, Any]:
        """Send the subpoena question to the cardholder over the first available channel
        (Judge only). Returns the channel used and the provider message id."""
        evaluation = await _evaluation(deps.store, evaluation_id)
        witness = evaluation.witness
        if witness is None:
            return {"sent": False, "reason": "no witness contact on the evaluation"}
        ws = await deps.store.get_workspace(evaluation.workspace_id)
        bank = ws.name.replace(" (local)", "") if ws else "your bank"
        user = deps.data.user(evaluation.transaction.user_id) or {}
        first = str(user.get("name", "")).split(" ")[0] or "there"
        t = evaluation.transaction
        body = (
            f"Hi {first}, this is {bank} Security. We're checking a {_money(t.amount)} payment to "
            f"{t.merchant.name}. {question.strip()} Reply YES or NO, or tell us more, and also "
            "send the 6-digit code we just texted you."
        )
        ctx = {
            "workspace_id": evaluation.workspace_id,
            "evaluation_id": evaluation_id,
            "subpoena_id": subpoena_id,
        }
        errors = []
        for name in channels:
            channel = Channel(name)
            if channel not in witness.allowed_channels:
                continue
            try:
                msg = await deps.witness.send_message(witness.phone, body, channel, context=ctx)
            except Exception as exc:  # fall back to the next channel
                errors.append(f"{channel}: {exc}")
                continue
            return {
                "sent": True,
                "channel": channel.value,
                "sid": msg.sid,
                "phone": witness.phone,
                "body": body,
            }
        return {"sent": False, "reason": "; ".join(errors) or "no allowed channel"}

    return server


async def _evaluation(store: Store, evaluation_id: str) -> Any:
    # The MCP server is trusted infrastructure; it looks the case up across workspaces.
    ev = await store.get_evaluation_any(evaluation_id)
    if ev is None:
        raise ValueError(f"unknown evaluation {evaluation_id}")
    return ev


def _register_resources(server: MCPServer, deps: McpDeps) -> None:
    @server.resource("user_profile://{user_id}/baselines", mime_type="application/json")
    def baselines(user_id: str) -> dict[str, Any]:
        """Historical devices, IPs, home geo, typical amounts and hours."""
        b = deps.data.baseline(user_id)
        return b.model_dump(mode="json") if b else {"user_id": user_id, "found": False}

    @server.resource("transactions://{user_id}/recent", mime_type="application/json")
    def recent(user_id: str) -> dict[str, Any]:
        """The user's last 50 transactions, newest first."""
        return {"user_id": user_id, "transactions": deps.data.recent_transactions(user_id, 50)}

    @server.resource("graph://{entity_id}/neighbors", mime_type="application/json")
    def neighbors(entity_id: str) -> dict[str, Any]:
        """Linked accounts, devices, IPs and payees, with risk flags."""
        return deps.data.graph_neighbors(entity_id)

    @server.resource("precedents://search/{q}", mime_type="application/json")
    def precedents(q: str) -> dict[str, Any]:
        """Similar past cases and their verdicts."""
        return {"query": q, "precedents": deps.data.precedents(q)}

    @server.resource("policy://{tenant_id}/active", mime_type="application/json")
    async def policy(tenant_id: str) -> dict[str, Any]:
        """Active thresholds and subpoena rules for the workspace."""
        p = await deps.store.get_active_policy(tenant_id) or Policy(workspace_id=tenant_id)
        return p.model_dump(mode="json")

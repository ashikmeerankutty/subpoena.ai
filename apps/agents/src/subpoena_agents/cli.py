"""Run a seed scenario through the courtroom and print the transcript.

uv run python -m subpoena_agents.cli auto_parts_deadlock --llm gemini [--reply "Yes ..." ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from subpoena_mcp.config import McpSettings
from subpoena_schemas import Evaluation, EvaluationRequest, Policy, Workspace
from subpoena_store import MemoryStore

from .config import CourtSettings
from .scheduler import LocalScheduler
from .wiring import build_courtroom


def _fmt(e: Any) -> str:
    p = e.payload
    head = f"{e.sequence:>3} {e.from_agent.value:>12} {e.type.value:<14}"
    tail = (
        f" [{e.model}, {e.tokens.input}+{e.tokens.output} tok, {e.latency_ms} ms]"
        if e.tokens
        else ""
    )
    if e.type.value == "FINDING":
        body = f"{p['id']} {p['severity']:<8} {p['supports']:<7} {p['detail']}"
    elif e.type.value in ("ARGUMENT", "REBUTTAL"):
        body = " | ".join(f"{c['text']} {c['cites']}" for c in p["claims"])
    elif e.type.value == "RULING":
        body = f"p_fraud={p['p_fraud']} -> {p['outcome']}; {p['rationale']} Q: {p.get('subpoena_question')}"
    elif e.type.value == "TOOL_CALL":
        body = p.get("tool") or p.get("resource")
    else:
        body = json.dumps(p, default=str)[:220]
    return head + body + tail


async def main(name: str, llm: str, replies: list[str]) -> None:
    seed = McpSettings().seed_dir
    scenario = next(
        s for s in json.loads((seed / "scenarios.json").read_text()) if s["name"] == name
    )
    store = MemoryStore()
    court = build_courtroom(CourtSettings(llm=llm), store, scheduler=LocalScheduler())
    ws = Workspace(name="Acme Bank")
    await store.put_workspace(ws)
    await store.put_policy(Policy(workspace_id=ws.id))
    req = EvaluationRequest.model_validate(scenario["request"])
    ev = Evaluation(
        workspace_id=ws.id, transaction=req.transaction(), witness=req.witness, policy_version=1
    )
    await store.put_evaluation(ev)
    result = await court.run_case(ev.evaluation_id)
    if replies and result and result.subpoena:
        sub = await store.get_subpoena(result.subpoena.id)
        assert sub is not None
        sub.pending_code = next(
            m.body.split("code is ")[1][:6]
            for m in await store.list_messages(sub.phone)
            if "code is" in m.body
        )
        # The first reply comes with the code; any others answer a follow-up question.
        for reply in replies:
            sub = await store.get_subpoena(sub.id)
            assert sub is not None
            sub.reply_text = f"{sub.reply_text}\n{reply}" if sub.reply_text else reply
            await store.put_subpoena(sub)
            result = await court.handle_inbound(sub.id)
        for m in await store.list_messages(sub.phone):
            print(f"  {m.direction.value:<8} {m.body}")
    for e in await store.list_events(ev.evaluation_id):
        print(_fmt(e))
    assert result is not None
    print(
        f"\n=> {result.status.value} verdict={result.verdict} p_fraud={result.p_fraud}\n{result.explanation}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--llm", default="scripted", choices=["scripted", "gemini"])
    ap.add_argument("--reply", action="append", default=[], help="repeat to answer a follow-up")
    a = ap.parse_args()
    asyncio.run(main(a.scenario, a.llm, a.reply))

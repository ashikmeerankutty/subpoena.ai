from __future__ import annotations

import json
from typing import Any

from subpoena_agents.config import CourtSettings
from subpoena_agents.courtroom import Courtroom
from subpoena_agents.scheduler import LocalScheduler
from subpoena_agents.wiring import build_courtroom
from subpoena_mcp.config import McpSettings
from subpoena_schemas import Evaluation, EvaluationRequest, Policy, Workspace
from subpoena_store import MemoryStore

SEED = McpSettings().seed_dir
SCENARIOS: dict[str, dict[str, Any]] = {
    s["name"]: s for s in json.loads((SEED / "scenarios.json").read_text())
}


class Harness:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.scheduler = LocalScheduler()  # timers recorded, fired manually in tests
        self.court: Courtroom = build_courtroom(
            CourtSettings(llm="scripted"), self.store, scheduler=self.scheduler
        )
        self.workspace = Workspace(name="Acme Bank")

    async def setup(self, policy: Policy | None = None) -> None:
        await self.store.put_workspace(self.workspace)
        await self.store.put_policy(policy or Policy(workspace_id=self.workspace.id))

    async def case(self, scenario: str, **overrides: Any) -> Evaluation:
        req = EvaluationRequest.model_validate(SCENARIOS[scenario]["request"] | overrides)
        ev = Evaluation(
            workspace_id=self.workspace.id,
            transaction=req.transaction(),
            witness=req.witness,
            options=req.options,
            policy_version=1,
        )
        await self.store.put_evaluation(ev)
        return ev

    async def last_code(self, phone: str) -> str:
        for m in reversed(await self.store.list_messages(phone)):
            if "verification code is" in m.body:
                return m.body.split("code is ")[1][:6]
        raise AssertionError("no code sent")

    async def reply(self, subpoena_id: str, *, text: str | None = None, code: str | None = None):
        sub = await self.store.get_subpoena(subpoena_id)
        assert sub is not None
        if text is not None:  # messages accumulate, as the API stores them
            sub.reply_text = f"{sub.reply_text}\n{text}" if sub.reply_text else text
        if code is not None:
            sub.pending_code = code
        await self.store.put_subpoena(sub)
        return await self.court.handle_inbound(subpoena_id)

    async def types(self, evaluation_id: str) -> list[str]:
        return [e.type.value for e in await self.store.list_events(evaluation_id)]

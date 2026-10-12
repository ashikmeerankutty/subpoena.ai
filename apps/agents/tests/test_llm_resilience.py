from __future__ import annotations

import asyncio
from typing import Any

import pytest
from google.genai import errors

from subpoena_agents import llm as llm_mod
from subpoena_agents.config import CourtSettings
from subpoena_agents.llm import GeminiLlm, LlmError, LlmResult
from subpoena_schemas import Agent, ArgumentOut


def rate_limited() -> errors.APIError:
    return errors.APIError(
        429,
        {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}},
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_mod, "BACKOFF", (0.0,) * 7)


def test_rate_limits_fall_back_to_second_model(monkeypatch: pytest.MonkeyPatch) -> None:
    g = GeminiLlm(CourtSettings(llm="gemini", gcp_project="p"))
    calls: list[str] = []

    async def once(
        self: Any, role: Agent, instruction: str, ctx: dict[str, Any], schema: Any, model: str
    ):
        calls.append(model)
        if model == "gemini-2.5-flash":
            raise rate_limited()
        return LlmResult(
            value=ArgumentOut(claims=[], summary="ok"), model=model, tokens=None, latency_ms=1
        )

    monkeypatch.setattr(GeminiLlm, "_once", once)
    out = asyncio.run(g.generate(Agent.PROSECUTOR, "i", {}, ArgumentOut))
    assert out.model == "gemini-2.5-flash-lite"
    assert calls == ["gemini-2.5-flash"] * 3 + ["gemini-2.5-flash-lite"]


def test_gives_up_with_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    g = GeminiLlm(CourtSettings(llm="gemini", gcp_project="p"))

    async def once(*_: Any, **__: Any):
        raise rate_limited()

    monkeypatch.setattr(GeminiLlm, "_once", once)
    with pytest.raises(LlmError):
        asyncio.run(g.generate(Agent.JUDGE, "i", {}, ArgumentOut))

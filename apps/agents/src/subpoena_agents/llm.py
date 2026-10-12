"""LLM backends. ``GeminiLlm`` runs each call through an ADK ``LlmAgent`` on Vertex AI with a
response schema; ``ScriptedLlm`` is a deterministic stand-in for tests and offline demos.

Both receive the same structured ``context``; Gemini sees it rendered as JSON under the role's
instruction, the scripted backend reads it directly.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel, ValidationError

from subpoena_schemas import (
    Agent,
    ArgumentOut,
    ClaimOut,
    ExpertFindingOut,
    ExpertReport,
    ExplanationOut,
    ReceiptOut,
    RulingOut,
    TestimonyClaims,
    TokenUsage,
)

from .config import CourtSettings

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """Model output failed twice (invalid or missing); the case must escalate."""


@dataclass
class LlmResult[R]:
    value: R
    model: str
    tokens: TokenUsage | None
    latency_ms: int


Image = tuple[bytes, str]  # (data, mime type)


class Llm(Protocol):
    async def generate(
        self,
        role: Agent,
        instruction: str,
        context: dict[str, Any],
        schema: type[T],
        images: list[Image] | None = None,
    ) -> LlmResult[T]: ...


def render(context: dict[str, Any]) -> str:
    return "CASE DATA (JSON):\n" + json.dumps(context, indent=1, default=str)


class GeminiLlm:
    def __init__(self, settings: CourtSettings) -> None:
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
        if settings.gcp_project:
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.gcp_project)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.vertex_location)
        self._s = settings
        self._slots = asyncio.Semaphore(settings.max_concurrent_llm_calls)

    def model_for(self, role: Agent) -> str:
        return self._s.pro_model if role is Agent.JUDGE else self._s.flash_model

    async def generate(
        self,
        role: Agent,
        instruction: str,
        context: dict[str, Any],
        schema: type[T],
        images: list[Image] | None = None,
    ) -> LlmResult[T]:
        from google.genai import errors

        models = [self.model_for(role), *self.fallbacks_for(role)]
        invalid = 0
        transient = 0
        while True:
            # After repeated rate limits, move to a model with its own quota pool.
            model = models[min(transient // RETRIES_PER_MODEL, len(models) - 1)]
            try:
                async with self._slots:
                    return await self._once(role, instruction, context, schema, model, images)
            except (ValidationError, ValueError, KeyError) as exc:
                invalid += 1  # retry once, then escalate (Spec §4)
                if invalid >= 2:
                    raise LlmError(f"{role.value}: invalid output after retry: {exc}") from exc
            except errors.APIError as exc:
                transient += 1
                if exc.code not in TRANSIENT_CODES or transient > len(BACKOFF):
                    raise LlmError(
                        f"{role.value}: model call failed: {exc.code} {exc.message}"
                    ) from exc
                await asyncio.sleep(BACKOFF[transient - 1] * (0.75 + random.random() / 2))

    def fallbacks_for(self, role: Agent) -> list[str]:
        if role is Agent.JUDGE:
            return [m for m in (self._s.judge_fallback_model,) if m]
        return [m for m in (self._s.flash_fallback_model,) if m]

    async def _once(
        self,
        role: Agent,
        instruction: str,
        context: dict[str, Any],
        schema: type[T],
        model: str,
        images: list[Image] | None = None,
    ) -> LlmResult[T]:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        thinking = self._s.judge_thinking_budget if role is Agent.JUDGE and "pro" in model else 0
        agent = LlmAgent(
            name=role.value,
            model=model,
            instruction=instruction,
            output_schema=schema,
            include_contents="none",
            generate_content_config=types.GenerateContentConfig(
                temperature=self._s.temperature,
                max_output_tokens=self._s.max_output_tokens + thinking,
                thinking_config=types.ThinkingConfig(thinking_budget=thinking),
            ),
        )
        runner = InMemoryRunner(agent=agent, app_name="courtroom")
        session = await runner.session_service.create_session(app_name="courtroom", user_id="court")
        parts = [types.Part(text=render(context))]
        parts += [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images or []]
        message = types.Content(role="user", parts=parts)
        started = time.perf_counter()
        text, usage = None, None
        async for event in runner.run_async(
            user_id="court", session_id=session.id, new_message=message
        ):
            if event.usage_metadata:
                usage = event.usage_metadata
            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(p.text or "" for p in event.content.parts)
        if not text:
            raise ValueError("empty model response")
        value = schema.model_validate_json(text)
        tokens = None
        if usage is not None:
            tokens = TokenUsage(
                input=usage.prompt_token_count or 0,
                output=(usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
            )
        latency = int((time.perf_counter() - started) * 1000)
        return LlmResult(value=value, model=model, tokens=tokens, latency_ms=latency)


TRANSIENT_CODES = {429, 500, 503, 504}
BACKOFF = (2.0, 4.0, 8.0, 4.0, 8.0, 16.0, 30.0)
RETRIES_PER_MODEL = 3

SEVERITY_WEIGHT = {"INFO": 0.0, "LOW": 0.25, "MEDIUM": 0.6, "HIGH": 1.0, "CRITICAL": 2.0}


class ScriptedLlm:
    """Deterministic courtroom: same inputs, same outputs. Mirrors what the prompts ask for."""

    model = "scripted"

    async def generate(
        self,
        role: Agent,
        instruction: str,
        context: dict[str, Any],
        schema: type[T],
        images: list[Image] | None = None,
    ) -> LlmResult[T]:
        value: BaseModel
        if schema is ExpertReport:
            value = ExpertReport(
                findings=[ExpertFindingOut.model_validate(s) for s in context["signals"]]
            )
        elif schema is ArgumentOut:
            value = self._argue(role, context)
        elif schema is RulingOut:
            value = self._rule(context)
        elif schema is ExplanationOut:
            value = self._explain(context)
        elif schema is TestimonyClaims:
            raw = re.sub(r"</?untrusted>", "", context["witness_message"])
            value = self._extract(raw)
        elif schema is ReceiptOut:
            value = self._read_receipt(images or [])
        else:
            raise LlmError(f"scripted backend has no output for {schema.__name__}")
        return LlmResult(
            value=cast(T, value),
            model=self.model,
            tokens=TokenUsage(input=0, output=0),
            latency_ms=0,
        )

    @staticmethod
    def _argue(role: Agent, ctx: dict[str, Any]) -> ArgumentOut:
        side = "FRAUD" if role is Agent.PROSECUTOR else "LEGIT"
        mine = [f for f in ctx["findings"] if f["supports"] == side]
        mine.sort(key=lambda f: -SEVERITY_WEIGHT[f["severity"]])
        claims = [ClaimOut(text=f["detail"], cites=[f["id"]]) for f in mine[:3]]
        if role is Agent.DEFENSE:
            for p in ctx.get("precedents", [])[:1]:
                if p["verdict"] == "APPROVE":
                    claims.append(
                        ClaimOut(
                            text=f"A similar case was approved: {p['summary']}", cites=[p["id"]]
                        )
                    )
        elif ctx.get("round", 0) == 0:
            # Prosecutors overreach; the citation rule strikes this.
            claims.append(
                ClaimOut(
                    text="The overall pattern feels like a classic account takeover.", cites=[]
                )
            )
        if not claims:
            claims = [ClaimOut(text="No evidence supports this position.", cites=[])]
        summary = "; ".join(c.text for c in claims[:2])
        return ArgumentOut(claims=claims, summary=summary[:240])

    @staticmethod
    def _rule(ctx: dict[str, Any]) -> RulingOut:
        testimony = ctx.get("testimony")
        cited = [f["id"] for f in ctx["findings"] if f["severity"] in ("HIGH", "CRITICAL")]
        receipt = (testimony or {}).get("receipt") or {}
        if (
            testimony
            and testimony["claims"].get("confirms_transaction")
            and receipt.get("result") == "MISMATCH"
        ):
            return RulingOut(
                p_fraud=0.7,
                confidence=0.6,
                cited_findings=cited,
                rationale="The cardholder confirmed the purchase, but the receipt they sent does not "
                "match this transaction, which undermines the testimony.",
            )
        if testimony and testimony["claims"].get("confirms_transaction"):
            return RulingOut(
                p_fraud=0.08,
                confidence=0.85,
                cited_findings=cited,
                rationale="The authenticated cardholder confirmed the purchase with a plausible reason "
                "that matches their purchase history; the remaining anomalies are explained.",
            )
        fraud = sum(
            SEVERITY_WEIGHT[f["severity"]] for f in ctx["findings"] if f["supports"] == "FRAUD"
        )
        legit = sum(
            SEVERITY_WEIGHT[f["severity"]] for f in ctx["findings"] if f["supports"] == "LEGIT"
        )
        p = round(1 / (1 + math.exp(-1.1 * (fraud - legit - 0.4))), 2)
        p = min(max(p, 0.01), 0.99)
        question = None
        if 0.15 < p < 0.85:
            question = "Did you make this purchase yourself, from a new device?"
        return RulingOut(
            p_fraud=p,
            confidence=0.7,
            cited_findings=cited,
            subpoena_question=question,
            rationale=f"Fraud-supporting evidence weighs {fraud:.1f} against {legit:.1f} for legitimacy.",
        )

    @staticmethod
    def _read_receipt(images: list[Image]) -> ReceiptOut:
        """No pixels here: a test "photo" is the receipt's fields as JSON; anything else is
        reported as not a receipt."""
        blank = {
            "merchant": None,
            "amount": None,
            "currency": None,
            "date": None,
            "order_reference": None,
        }
        try:
            fields = json.loads(images[0][0])
            return ReceiptOut.model_validate({**blank, "is_receipt": True, **fields})
        except (IndexError, ValueError, UnicodeDecodeError):
            return ReceiptOut(is_receipt=False, **blank)

    @staticmethod
    def _explain(ctx: dict[str, Any]) -> ExplanationOut:
        verdict = ctx["decision"]["verdict"] or "HOLD"
        reason = ctx["decision"]["reason"]
        merchant = ctx["transaction"]["merchant"]["name"]
        amount = ctx["transaction"]["amount"]
        notice = {
            "APPROVE": f"Your ${amount} payment to {merchant} was approved. Thanks for confirming.",
            "BLOCK": f"We blocked a ${amount} payment to {merchant} to protect your account. "
            "Please contact us if this was you.",
        }.get(verdict, f"Your ${amount} payment to {merchant} is on hold while we review it.")
        sar = None
        if verdict == "BLOCK":
            sar = f"Blocked ${amount} {ctx['transaction']['type']} to {merchant}. {reason}"
        return ExplanationOut(
            bank_explanation=f"{verdict}: {reason}", cardholder_notice=notice, sar_draft=sar
        )

    @staticmethod
    def _extract(text: str) -> TestimonyClaims:
        t = text.strip().lower()
        yes = re.match(r"^(yes|yeah|yep|y\b|it was me|that was me|i did)", t)
        no = re.match(r"^(no|nope|n\b|not me|i didn)", t)
        reason = re.sub(r"^(yes|yeah|yep|no|nope)[,.!\s-]*", "", text.strip(), flags=re.I) or None
        return TestimonyClaims(
            confirms_transaction=True if yes else False if no else None,
            stated_reason=reason,
            mentions_travel=bool(re.search(r"travel|trip|abroad|holiday|vacation", t)),
            sentiment="calm",
        )

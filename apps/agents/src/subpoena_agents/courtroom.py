"""The courtroom (Spec §4-§6): debate, ruling, subpoena, testimony and re-ruling.

Every step is persisted as a ``PipelineEvent`` so the Console can replay the case. Agents
reach data only through their own MCP sessions; the outcome is always decided by the
policy functions from the Judge's ``p_fraud``, never by free text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from subpoena_api.webhooks import BankNotifier
from subpoena_mcp.client import AgentSession, McpConnector
from subpoena_schemas import (
    Agent,
    ArgumentOut,
    Channel,
    DebateSummaryItem,
    Decision,
    DeliveryStatus,
    EvaluationStatus,
    EventType,
    EvidenceFinding,
    ExpertReport,
    ExplanationOut,
    Outcome,
    PipelineEvent,
    Policy,
    ReceiptCheck,
    ReceiptOut,
    ReceiptResult,
    RulingOut,
    Severity,
    Subpoena,
    SubpoenaState,
    Testimony,
    TestimonyClaims,
    TestimonyOutcome,
    Verdict,
    WitnessAuthResult,
    decide,
    decide_after_testimony,
    utcnow,
)
from subpoena_schemas.evaluation import Evaluation
from subpoena_store import (
    MediaStore,
    MemoryMediaStore,
    Store,
    case_text,
    payment_key,
    precedent_for,
)

from . import evidence, pricing, prompts, receipts
from .llm import Llm, LlmError, LlmResult
from .scheduler import Scheduler
from .screening import Screener

log = logging.getLogger(__name__)

MAX_CODE_ATTEMPTS = 3

SCAM_PROMPT = "for example someone saying they're from your bank or the police"
SCAM_WARNING = (
    "Your bank and the police will never ask you to move money or to keep a payment secret."
)
# One follow-up at most, when the first reply leaves the answer open (Spec §6).
FOLLOW_UPS: dict[tuple[str, ...], str] = {
    ("confirm",): "Sorry, we couldn't tell from your reply. Did you make this payment yourself? "
    "Reply YES or NO.",
    ("reason",): "Thanks. One more check: what did you buy, or what was this payment for?",
    ("scam",): "Thanks. One more check to keep you safe: has anyone asked you or told you to "
    f"make this payment, {SCAM_PROMPT}? Reply YES or NO.",
    ("confirm", "scam"): "Sorry, we couldn't tell from your reply. Did you make this payment "
    f"yourself, and has anyone asked you or told you to make it, {SCAM_PROMPT}?",
    ("reason", "scam"): "Thanks. Two quick checks to keep you safe: what is this payment for, "
    f"and has anyone asked you or told you to make it, {SCAM_PROMPT}?",
}


class Courtroom:
    def __init__(
        self,
        *,
        store: Store,
        mcp: McpConnector,
        llm: Llm,
        screener: Screener,
        notifier: BankNotifier,
        scheduler: Scheduler,
        max_rounds: int = 2,
        media: MediaStore | None = None,
    ) -> None:
        self.store = store
        self.mcp = mcp
        self.llm = llm
        self.screener = screener
        self.notifier = notifier
        self.scheduler = scheduler
        self.max_rounds = max_rounds
        self.media = media or MemoryMediaStore()
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ helpers

    async def emit(
        self,
        ev: Evaluation,
        frm: Agent,
        type_: EventType,
        payload: dict[str, Any],
        *,
        to: Agent | None = None,
        round_: int | None = None,
        result: LlmResult[Any] | None = None,
        latency_ms: int | None = None,
    ) -> PipelineEvent:
        event = PipelineEvent(
            evaluation_id=ev.evaluation_id,
            sequence=0,
            round=round_,
            from_agent=frm,
            to_agent=to,
            type=type_,
            payload=payload,
            model=result.model if result else None,
            tokens=result.tokens if result else None,
            latency_ms=result.latency_ms if result else latency_ms,
        )
        return await self.store.append_event(event)

    async def _tool(
        self, ev: Evaluation, s: AgentSession, name: str, **args: Any
    ) -> dict[str, Any]:
        started = time.perf_counter()
        out = await s.call(name, **args)
        await self.emit(
            ev,
            s.agent,
            EventType.TOOL_CALL,
            {"tool": name, "arguments": args, "result": out},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return out

    async def _read(
        self, ev: Evaluation, s: AgentSession, uri: str, summary: Any = None
    ) -> dict[str, Any]:
        started = time.perf_counter()
        out = await s.read(uri)
        await self.emit(
            ev,
            s.agent,
            EventType.TOOL_CALL,
            {"resource": uri, "result": summary(out) if summary else out},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return out

    async def _save(self, ev: Evaluation, **changes: Any) -> Evaluation:
        if "status" in changes or "verdict" in changes:
            changes["cost_usd"], changes["tokens"] = pricing.cost(
                await self.store.list_events(ev.evaluation_id)
            )
        updated = ev.model_copy(update={**changes, "updated_at": utcnow()})
        await self.store.put_evaluation(updated)
        return updated

    # ------------------------------------------------------------------ Tier 1

    async def run_case(self, evaluation_id: str) -> Evaluation | None:
        ev = await self.store.get_evaluation_any(evaluation_id)
        if ev is None or ev.status is not EvaluationStatus.RECEIVED:
            return ev  # unknown or already handled (Pub/Sub redelivery)
        ev = await self._save(ev, status=EvaluationStatus.IN_DEBATE)
        try:
            return await self._debate(ev)
        except Exception as exc:  # model/tool failure -> retry once happened already -> ESCALATE
            log.exception("courtroom failed for %s", evaluation_id)
            await self.emit(
                ev, Agent.SYSTEM, EventType.ERROR, {"error": f"{type(exc).__name__}: {exc}"}
            )
            decision = Decision(
                outcome=Outcome.ESCALATE,
                verdict=Verdict.HOLD,
                status=EvaluationStatus.ESCALATED,
                reason=f"Courtroom error ({type(exc).__name__}); held for analyst review",
            )
            fresh = await self.store.get_evaluation_any(evaluation_id) or ev
            return await self._finalize(
                fresh, decision, p_fraud=fresh.p_fraud, rationale=decision.reason, explain=False
            )

    async def _debate(self, ev: Evaluation) -> Evaluation:
        policy = await self._policy(ev)
        txn = evidence.transaction_view(ev)

        # Discovery: Clerk builds the evidence bundle.
        async with self.mcp.session(Agent.CLERK) as clerk:
            uid = ev.transaction.user_id
            baseline = await self._read(ev, clerk, f"user_profile://{uid}/baselines")
            recent_doc = await self._read(
                ev,
                clerk,
                f"transactions://{uid}/recent",
                summary=lambda d: {
                    "count": len(d["transactions"]),
                    "latest": d["transactions"][:3],
                },
            )
        recent = recent_doc["transactions"]

        # Expert Witnesses in parallel, each through its own MCP endpoint.
        reports = await asyncio.gather(
            *(self._expert(ev, agent, txn, baseline, recent) for agent in evidence.EXPERTS)
        )
        findings: list[EvidenceFinding] = []
        for agent, report in zip(evidence.EXPERTS, reports, strict=True):
            for f in report.findings:
                finding = EvidenceFinding(
                    id=f"F{len(findings) + 1}",
                    agent=agent,
                    type=f.type,
                    severity=Severity(f.severity),
                    supports=f.supports,
                    detail=f.detail,
                    source_ref=f"mcp:{agent.value}",
                )
                findings.append(finding)
                await self.emit(ev, agent, EventType.FINDING, finding.model_dump(mode="json"))
        ev = await self._save(ev, findings=findings)
        finding_view = [f.model_dump(mode="json", exclude={"source_ref"}) for f in findings]

        # Defense precedent search (embedding similarity over this workspace's rulings + seed).
        async with self.mcp.session(Agent.DEFENSE) as defense:
            q = quote(case_text(ev, with_outcome=False)[0], safe="")
            uri = f"precedents://{ev.workspace_id}/search/{q}/excluding/{payment_key(ev)}"
            found = await self._read(ev, defense, uri)
        # Short citation IDs for the debate; the library ID stays alongside.
        precedents = [
            {**p, "precedent_id": p["id"], "id": f"P{i}"}
            for i, p in enumerate(found["precedents"], start=1)
        ]
        valid_ids = {f.id for f in findings} | {p["id"] for p in precedents}

        # Opening arguments and rebuttals.
        transcript: dict[Agent, list[dict[str, Any]]] = {Agent.PROSECUTOR: [], Agent.DEFENSE: []}
        latest: dict[Agent, ArgumentOut] = {}
        for rnd in range(self.max_rounds):
            ctx_base = {
                "transaction": txn,
                "findings": finding_view,
                "precedents": precedents,
                "round": rnd,
            }
            pros, dfn = await asyncio.gather(
                self._argue(
                    ev,
                    Agent.PROSECUTOR,
                    prompts.PROSECUTOR,
                    ctx_base,
                    latest.get(Agent.DEFENSE),
                    rnd,
                ),
                self._argue(
                    ev, Agent.DEFENSE, prompts.DEFENSE, ctx_base, latest.get(Agent.PROSECUTOR), rnd
                ),
            )
            for agent, arg in ((Agent.PROSECUTOR, pros), (Agent.DEFENSE, dfn)):
                kept = await self._strike(ev, agent, arg, valid_ids, rnd)
                transcript[agent].append({"round": rnd, "claims": kept, "summary": arg.summary})
                latest[agent] = arg

        debate_summary = [
            DebateSummaryItem(
                agent=Agent.PROSECUTOR,
                position=Verdict.BLOCK,
                summary=latest[Agent.PROSECUTOR].summary,
            ),
            DebateSummaryItem(
                agent=Agent.DEFENSE, position=Verdict.APPROVE, summary=latest[Agent.DEFENSE].summary
            ),
        ]
        ev = await self._save(ev, debate_summary=debate_summary)

        # Ruling.
        judge_ctx = {
            "transaction": txn,
            "findings": finding_view,
            "precedents": precedents,
            "prosecution": transcript[Agent.PROSECUTOR],
            "defense": transcript[Agent.DEFENSE],
            "policy_thresholds": policy.thresholds.model_dump(),
        }
        ruling = await self.llm.generate(Agent.JUDGE, prompts.JUDGE, judge_ctx, RulingOut)
        r = ruling.value
        witness_channels = ev.witness.allowed_channels if ev.witness else []
        decision = decide(
            r.p_fraud,
            policy=policy,
            amount=ev.transaction.amount,
            witness_channels=witness_channels,
        )
        await self.emit(
            ev,
            Agent.JUDGE,
            EventType.RULING,
            {
                **r.model_dump(),
                "outcome": decision.outcome,
                "reason": decision.reason,
                "policy_version": policy.version,
            },
            result=ruling,
        )
        ev = await self._save(ev, p_fraud=r.p_fraud, rationale=r.rationale)

        if decision.outcome is Outcome.SUBPOENA:
            question = r.subpoena_question or "Did you make this purchase yourself?"
            return await self._subpoena(ev, policy, question)
        return await self._finalize(ev, decision, p_fraud=r.p_fraud, rationale=r.rationale)

    async def _expert(
        self,
        ev: Evaluation,
        agent: Agent,
        txn: dict[str, Any],
        baseline: dict[str, Any],
        recent: list[dict[str, Any]],
    ) -> ExpertReport:
        t = ev.transaction
        tools: dict[str, Any] = {}
        async with self.mcp.session(agent) as s:
            if agent is Agent.GEO and t.metadata.ip_address:
                tools["geo_velocity"] = await self._tool(
                    ev,
                    s,
                    "geo_velocity",
                    user_id=t.user_id,
                    ip_address=t.metadata.ip_address,
                    timestamp=t.occurred_at.isoformat(),
                )
                tools["home_country"] = (baseline.get("home") or {}).get("country")
                signals = evidence.geo_signals(ev, tools)
            elif agent is Agent.DEVICE:
                if t.metadata.ip_address:
                    tools["query_asn_reputation"] = await self._tool(
                        ev, s, "query_asn_reputation", ip_address=t.metadata.ip_address
                    )
                signals = evidence.device_signals(ev, tools, baseline)
            elif agent is Agent.VELOCITY:
                signals = evidence.velocity_signals(ev, baseline, recent)
                tools["recent_count"] = len(recent)
            elif agent is Agent.MERCHANT:
                tools["validate_merchant"] = await self._tool(
                    ev, s, "validate_merchant", merchant_name=t.merchant.name, mcc=t.merchant.mcc
                )
                signals = evidence.merchant_signals(tools)
            elif agent is Agent.GRAPH:
                graphs = {}
                for entity in filter(None, (t.metadata.device_fingerprint, t.metadata.ip_address)):
                    graphs[entity] = await self._read(ev, s, f"graph://{entity}/neighbors")
                signals = evidence.graph_signals(graphs)
            else:
                signals = evidence.geo_signals(ev, tools)
        ctx = {
            "transaction": txn,
            "baseline": _baseline_view(baseline),
            "tool_results": tools,
            "signals": signals,
        }
        result = await self.llm.generate(
            agent, prompts.expert_instruction(agent), ctx, ExpertReport
        )
        return result.value

    async def _argue(
        self,
        ev: Evaluation,
        agent: Agent,
        instruction: str,
        ctx: dict[str, Any],
        opponent: ArgumentOut | None,
        rnd: int,
    ) -> ArgumentOut:
        if opponent is not None:
            ctx = {**ctx, "opponent_latest_argument": opponent.model_dump()}
        result = await self.llm.generate(agent, instruction, ctx, ArgumentOut)
        await self.emit(
            ev,
            agent,
            EventType.ARGUMENT if rnd == 0 else EventType.REBUTTAL,
            {
                "position": "BLOCK" if agent is Agent.PROSECUTOR else "APPROVE",
                "claims": [c.model_dump() for c in result.value.claims],
                "summary": result.value.summary,
            },
            to=Agent.JUDGE,
            round_=rnd,
            result=result,
        )
        return result.value

    async def _strike(
        self, ev: Evaluation, agent: Agent, arg: ArgumentOut, valid: set[str], rnd: int
    ) -> list[dict[str, Any]]:
        """Citation rule: a claim with no valid finding/precedent ID never reaches the Judge."""
        kept = []
        for claim in arg.claims:
            cites = [c for c in claim.cites if c in valid]
            if cites:
                kept.append({"text": claim.text, "cites": cites})
            else:
                await self.emit(
                    ev,
                    Agent.SYSTEM,
                    EventType.CLAIM_STRUCK,
                    {
                        "agent": agent,
                        "claim": claim.text,
                        "cites": claim.cites,
                        "reason": "no valid finding or precedent citation",
                    },
                    round_=rnd,
                )
        return kept

    async def _policy(self, ev: Evaluation) -> Policy:
        return await self.store.get_active_policy(ev.workspace_id) or Policy(
            workspace_id=ev.workspace_id
        )

    # ------------------------------------------------------------------ Tier 2: subpoena

    async def _subpoena(self, ev: Evaluation, policy: Policy, question: str) -> Evaluation:
        assert ev.witness is not None
        phone = ev.witness.phone
        now = utcnow()
        sub = Subpoena(
            workspace_id=ev.workspace_id,
            evaluation_id=ev.evaluation_id,
            user_id=ev.transaction.user_id,
            phone=phone,
            question=question,
            channel=Channel.SMS,
            sent_at=now,
            expires_at=now + timedelta(seconds=policy.subpoena.timeout_seconds),
            scam_check=evidence.is_push_payment(ev),
        )

        # Bailiff: SIM-swap check before the witness is contacted.
        async with self.mcp.session(Agent.BAILIFF) as bailiff:
            lookup = await self._tool(ev, bailiff, "lookup_phone", user_id=sub.user_id, phone=phone)
        sub.lookup = lookup
        if lookup.get("recent_sim_swap"):
            sub.state = SubpoenaState.AUTH_FAILED
            await self.store.put_subpoena(sub)
            await self.emit(
                ev,
                Agent.BAILIFF,
                EventType.WITNESS_AUTH,
                {
                    "result": WitnessAuthResult.FAILED,
                    "subpoena_id": sub.id,
                    "check": "lookup",
                    "reason": (
                        f"SIM swapped on {lookup.get('last_sim_swap')}, within {lookup.get('window_days')} days"
                        if lookup.get("sim_swap_checked", True)
                        else "SIM-swap status unavailable from the carrier"
                    ),
                },
                to=Agent.JUDGE,
            )
            ev = await self._save(ev, subpoena=sub.ref())
            decision = decide_after_testimony(
                policy=policy,
                auth=WitnessAuthResult.FAILED,
                outcome=TestimonyOutcome.CONFIRMED,
                p_fraud_rerule=ev.p_fraud,
            )
            await self.notifier.notify(
                ev, "witness_auth.failed", {"subpoena_id": sub.id, "check": "lookup"}
            )
            return await self._finalize(ev, decision, p_fraud=ev.p_fraud, rationale=decision.reason)

        async with self.mcp.session(Agent.JUDGE) as judge:
            sent = await self._tool(
                ev,
                judge,
                "issue_subpoena",
                evaluation_id=ev.evaluation_id,
                subpoena_id=sub.id,
                question=question,
                channels=[c.value for c in policy.subpoena.channels],
            )
        if not sent.get("sent"):
            decision = Decision(
                outcome=Outcome.ESCALATE,
                verdict=Verdict.HOLD,
                status=EvaluationStatus.ESCALATED,
                reason=f"Subpoena could not be delivered ({sent.get('reason')}); held for analyst review",
            )
            return await self._finalize(ev, decision, p_fraud=ev.p_fraud, rationale=decision.reason)
        sub.channel = Channel(sent["channel"])
        sub.channels_tried = [Channel(c) for c in sent.get("tried", [sent["channel"]])]
        sub.twilio_sid = sent.get("sid")
        await self.store.put_subpoena(sub)

        async with self.mcp.session(Agent.BAILIFF) as bailiff:
            await self._tool(
                ev,
                bailiff,
                "send_verification",
                user_id=sub.user_id,
                phone=phone,
                evaluation_id=ev.evaluation_id,
                subpoena_id=sub.id,
            )

        await self.emit(
            ev,
            Agent.JUDGE,
            EventType.SUBPOENA_SENT,
            {
                "subpoena_id": sub.id,
                "channel": sub.channel,
                "question": question,
                "expires_at": sub.expires_at.isoformat(),
            },
            to=Agent.WITNESS,
        )
        ev = await self._save(ev, status=EvaluationStatus.AWAITING_TESTIMONY, subpoena=sub.ref())
        await self.scheduler.schedule_timeout(sub.id, sub.expires_at)
        await self.notifier.notify(
            ev,
            "subpoena.sent",
            {
                "subpoena_id": sub.id,
                "channel": sub.channel,
                "expires_at": sub.expires_at.isoformat(),
            },
        )
        return ev

    async def handle_inbound(self, subpoena_id: str) -> Evaluation | None:
        """Called after the API stored a witness reply and/or code on the subpoena."""
        lock = self._locks.setdefault(subpoena_id, asyncio.Lock())
        async with lock:
            return await self._handle_inbound(subpoena_id)

    async def _handle_inbound(self, subpoena_id: str) -> Evaluation | None:
        sub = await self.store.get_subpoena(subpoena_id)
        if sub is None or sub.state is not SubpoenaState.AWAITING_REPLY:
            return None
        ev = await self.store.get_evaluation_any(sub.evaluation_id)
        if ev is None:
            return None
        policy = await self._policy(ev)

        undelivered = sub.delivery_status in (DeliveryStatus.FAILED, DeliveryStatus.UNDELIVERED)
        if undelivered and not (sub.reply_text or sub.pending_code or sub.code_verified):
            return await self._redeliver(ev, sub, policy)

        if sub.pending_code and not sub.code_verified:
            code, sub.pending_code = sub.pending_code, None
            async with self.mcp.session(Agent.BAILIFF) as bailiff:
                check = await self._tool(
                    ev, bailiff, "check_verification", phone=sub.phone, code=code
                )
            sub.code_attempts += 1
            if check.get("status") == "approved":
                sub.code_verified = True
                await self.emit(
                    ev,
                    Agent.BAILIFF,
                    EventType.WITNESS_AUTH,
                    {
                        "result": WitnessAuthResult.PASSED,
                        "subpoena_id": sub.id,
                        "check": "lookup+verify",
                        "lookup": _lookup_view(sub.lookup),
                    },
                    to=Agent.JUDGE,
                )
            elif sub.code_attempts >= MAX_CODE_ATTEMPTS or check.get("status") in (
                "max_attempts_reached",
                "expired",
            ):
                sub.state = SubpoenaState.CODE_FAILED
                await self.store.put_subpoena(sub)
                await self.emit(
                    ev,
                    Agent.BAILIFF,
                    EventType.WITNESS_AUTH,
                    {
                        "result": WitnessAuthResult.FAILED,
                        "subpoena_id": sub.id,
                        "check": "verify",
                        "reason": f"verification {check.get('status')} after {sub.code_attempts} attempt(s)",
                    },
                    to=Agent.JUDGE,
                )
                await self._reply(
                    sub,
                    "We couldn't verify your identity, so the payment stays blocked. "
                    "Please call the number on the back of your card.",
                )
                await self.notifier.notify(
                    ev, "witness_auth.failed", {"subpoena_id": sub.id, "check": "verify"}
                )
                decision = decide_after_testimony(
                    policy=policy,
                    auth=WitnessAuthResult.FAILED,
                    outcome=TestimonyOutcome.CONFIRMED,
                    p_fraud_rerule=ev.p_fraud,
                )
                return await self._finalize(
                    ev, decision, p_fraud=ev.p_fraud, rationale=decision.reason
                )
            else:
                await self._reply(
                    sub, "That code didn't match. Please send the 6-digit code from our text."
                )
        await self.store.put_subpoena(sub)

        if not (sub.code_verified and sub.reply_text):
            # On a call the witness is asked for their answer right after the code.
            if sub.code_verified and not sub.reply_text and sub.channel is not Channel.VOICE:
                await self._reply(
                    sub, "Thanks, you're verified. Was this payment yours? Reply YES or NO."
                )
            elif sub.reply_text and not sub.code_verified and sub.code_attempts == 0:
                await self._reply(
                    sub,
                    "Thanks. To confirm it's really you, please send the 6-digit code we texted.",
                )
            return ev
        if sub.follow_up and sub.follow_up_answer() is None:
            return ev  # still waiting for the answer to the follow-up question
        return await self._admit(ev, sub, policy)

    async def _read_receipt(
        self, ev: Evaluation, sub: Subpoena
    ) -> tuple[ReceiptCheck | None, LlmResult[ReceiptOut] | None]:
        """Read the first photo the witness sent and compare it with the transaction."""
        photo = next((m for m in sub.media if m.content_type.startswith("image/")), None)
        if photo is None:
            return None, None

        def unreadable(reason: str) -> ReceiptCheck:
            return ReceiptCheck(
                media_id=photo.id, result=ReceiptResult.UNREADABLE, reasons=[reason]
            )

        found = await self.media.get(f"{sub.workspace_id}/{photo.id}")
        if found is None:
            return unreadable("The photo is no longer available"), None
        try:
            read = await self.llm.generate(
                Agent.WITNESS,
                prompts.RECEIPT,
                {"task": "Read the attached photo."},
                ReceiptOut,
                images=[found],
            )
        except LlmError as exc:
            log.warning("receipt read failed for %s: %s", sub.id, exc)
            return unreadable("The photo could not be read"), None
        return receipts.compare(photo.id, read.value, ev.transaction), read

    async def _extract(self, sub: Subpoena) -> LlmResult[TestimonyClaims]:
        assert sub.reply_text is not None
        ctx: dict[str, Any] = {"witness_message": f"<untrusted>{sub.reply_text}</untrusted>"}
        if sub.follow_up:
            ctx["follow_up"] = {
                "question": sub.follow_up,
                "asks": sub.follow_up_asks,
                "answer": f"<untrusted>{sub.follow_up_answer() or ''}</untrusted>",
            }
        return await self.llm.generate(Agent.WITNESS, prompts.EXTRACTOR, ctx, TestimonyClaims)

    async def _follow_up(
        self, ev: Evaluation, sub: Subpoena, asks: list[str], extracted: LlmResult[TestimonyClaims]
    ) -> Evaluation:
        """The reply left the answer open: ask one more question before the testimony counts."""
        question = FOLLOW_UPS[tuple(asks)]
        sub.follow_up, sub.follow_up_asks = question, asks
        sub.follow_up_offset = len(sub.reply_text or "")
        await self.store.put_subpoena(sub)
        await self._reply(sub, question)
        await self.emit(
            ev,
            Agent.JUDGE,
            EventType.SUBPOENA_SENT,
            {
                "subpoena_id": sub.id,
                "follow_up": True,
                "asks": asks,
                "question": question,
                "claims_so_far": extracted.value.model_dump(),
            },
            to=Agent.WITNESS,
            result=extracted,
        )
        return ev

    async def _admit(self, ev: Evaluation, sub: Subpoena, policy: Policy) -> Evaluation:
        """Testimony is authenticated: screen, extract, re-rule (Spec §5 'After testimony')."""
        assert sub.reply_text is not None
        screening = await self.screener.screen(sub.reply_text)
        extracted = await self._extract(sub)
        claims = extracted.value
        asks = [] if screening.flagged else _follow_up_asks(sub, claims)
        if asks:
            return await self._follow_up(ev, sub, asks, extracted)

        sub.state = SubpoenaState.ADMITTED
        sub.responded_at = utcnow()
        await self.store.put_subpoena(sub)
        follow_up = (
            {"question": sub.follow_up, "answer": sub.follow_up_answer()} if sub.follow_up else None
        )
        receipt, read = await self._read_receipt(ev, sub)
        testimony = Testimony(
            subpoena_id=sub.id,
            raw_text=sub.reply_text,
            claims=claims,
            media_refs=[m.id for m in sub.media],
            receipt=receipt,
            witness_auth_result=WitnessAuthResult.PASSED,
            flagged_by_screening=screening.flagged,
            screening_reasons=screening.reasons,
            received_at=sub.responded_at,
        )
        await self.emit(
            ev,
            Agent.WITNESS,
            EventType.TESTIMONY,
            {
                "subpoena_id": sub.id,
                "claims": claims.model_dump(),
                "flagged": screening.flagged,
                "screening": {"engine": screening.engine, "reasons": screening.reasons},
                "raw_text": sub.reply_text,
                "follow_up": follow_up,
            },
            to=Agent.JUDGE,
            result=extracted,
        )
        if receipt is not None:
            await self.emit(
                ev,
                Agent.WITNESS,
                EventType.EVIDENCE,
                {"kind": "receipt", "subpoena_id": sub.id, **receipt.model_dump(mode="json")},
                to=Agent.JUDGE,
                result=read,
            )
        ev = await self._save(ev, testimony=testimony)
        await self.notifier.notify(
            ev,
            "testimony.received",
            {"subpoena_id": sub.id, "confirms_transaction": claims.confirms_transaction},
        )

        if claims.confirms_transaction is False:
            decision = decide_after_testimony(
                policy=policy, auth=WitnessAuthResult.PASSED, outcome=TestimonyOutcome.DENIED
            )
            await self._reply(
                sub, "Thank you. We've blocked the payment and will help you replace your card."
            )
            return await self._finalize(
                ev, decision, p_fraud=max(ev.p_fraud or 0, 0.95), rationale=decision.reason
            )
        if claims.confirms_transaction is None:
            decision = Decision(
                outcome=Outcome.ESCALATE,
                verdict=Verdict.HOLD,
                status=EvaluationStatus.ESCALATED,
                reason="Witness reply did not clearly confirm or deny; held for analyst review",
            )
            await self._reply(sub, "Thanks. An analyst will review this payment shortly.")
            return await self._finalize(ev, decision, p_fraud=ev.p_fraud, rationale=decision.reason)
        if claims.told_to_pay:
            # The real cardholder, talked into paying: their "yes" is the scam working.
            decision = Decision(
                outcome=Outcome.ESCALATE,
                verdict=Verdict.HOLD,
                status=EvaluationStatus.ESCALATED,
                reason="The cardholder confirmed the payment but says someone told them to make it: "
                "a possible authorised push-payment scam. Held for a specialist to call them",
            )
            await self._reply(
                sub,
                "Thank you for telling us. We've paused this payment to protect you. "
                f"{SCAM_WARNING} Please call us on the number on the back of your card before "
                "you send any money.",
            )
            return await self._finalize(ev, decision, p_fraud=ev.p_fraud, rationale=decision.reason)

        # Confirmed: the Judge re-rules once with the testimony as new evidence.
        events = await self.store.list_events(ev.evaluation_id)
        ctx = {
            "transaction": evidence.transaction_view(ev),
            "findings": [f.model_dump(mode="json", exclude={"source_ref"}) for f in ev.findings],
            "previous_ruling": next(
                (e.payload for e in reversed(events) if e.type is EventType.RULING), None
            ),
            "testimony": {
                "witness_authenticated": True,
                "claims": claims.model_dump(),
                "raw_text": None
                if screening.flagged
                else f"<untrusted>{sub.reply_text}</untrusted>",
                "screening_flagged": screening.flagged,
                "follow_up": {
                    "question": sub.follow_up,
                    "answer": f"<untrusted>{sub.follow_up_answer() or ''}</untrusted>",
                }
                if sub.follow_up and not screening.flagged
                else None,
                "receipt": receipt.model_dump(mode="json", exclude={"media_id"})
                if receipt
                else None,
            },
            "policy_thresholds": policy.thresholds.model_dump(),
        }
        ruling = await self.llm.generate(Agent.JUDGE, prompts.JUDGE, ctx, RulingOut)
        r = ruling.value
        decision = decide_after_testimony(
            policy=policy,
            auth=WitnessAuthResult.PASSED,
            outcome=TestimonyOutcome.CONFIRMED,
            p_fraud_rerule=r.p_fraud,
        )
        if screening.flagged and decision.outcome is Outcome.APPROVE:
            decision = Decision(
                outcome=Outcome.ESCALATE,
                verdict=Verdict.HOLD,
                status=EvaluationStatus.ESCALATED,
                reason="Testimony was flagged by screening (possible prompt injection); an analyst must confirm",
            )
        if (
            receipt is not None
            and receipt.result is ReceiptResult.MISMATCH
            and decision.outcome is Outcome.APPROVE
        ):
            decision = Decision(
                outcome=Outcome.ESCALATE,
                verdict=Verdict.HOLD,
                status=EvaluationStatus.ESCALATED,
                reason="The witness's receipt does not match this transaction; an analyst must confirm",
            )
        await self.emit(
            ev,
            Agent.JUDGE,
            EventType.RULING,
            {
                **r.model_dump(),
                "outcome": decision.outcome,
                "reason": decision.reason,
                "re_ruling": True,
                "policy_version": policy.version,
            },
            result=ruling,
        )
        await self._reply(
            sub,
            "Thanks for confirming. Your payment is approved."
            if decision.verdict is Verdict.APPROVE
            else "Thanks. An analyst will review this payment shortly.",
        )
        return await self._finalize(ev, decision, p_fraud=r.p_fraud, rationale=r.rationale)

    async def _redeliver(self, ev: Evaluation, sub: Subpoena, policy: Policy) -> Evaluation:
        """The provider reported the subpoena undelivered (WhatsApp window closed, call not
        answered): send it again on the next channel the policy allows. The code already went
        out by SMS, and the original deadline stands."""
        failed = sub.channel
        remaining = [c.value for c in policy.subpoena.channels if c not in sub.channels_tried]
        sent: dict[str, Any] = {"sent": False, "reason": "no channels left"}
        if remaining:
            async with self.mcp.session(Agent.JUDGE) as judge:
                sent = await self._tool(
                    ev,
                    judge,
                    "issue_subpoena",
                    evaluation_id=ev.evaluation_id,
                    subpoena_id=sub.id,
                    question=sub.question,
                    channels=remaining,
                )
        sub.channels_tried += [Channel(c) for c in sent.get("tried", [])]
        if sent.get("sent"):
            sub.channel = Channel(sent["channel"])
            sub.twilio_sid = sent.get("sid")
            sub.delivery_status = DeliveryStatus.QUEUED
        await self.store.put_subpoena(sub)
        await self.emit(
            ev,
            Agent.JUDGE,
            EventType.SUBPOENA_SENT,
            {
                "subpoena_id": sub.id,
                "channel": sub.channel if sent.get("sent") else None,
                "fallback_from": failed,
                "delivered": bool(sent.get("sent")),
                "reason": None if sent.get("sent") else sent.get("reason"),
                "expires_at": sub.expires_at.isoformat(),
            },
            to=Agent.WITNESS,
        )
        return await self._save(ev, subpoena=sub.ref())

    async def handle_timeout(self, subpoena_id: str) -> Evaluation | None:
        async with self._locks.setdefault(subpoena_id, asyncio.Lock()):
            return await self._handle_timeout(subpoena_id)

    async def _handle_timeout(self, subpoena_id: str) -> Evaluation | None:
        sub = await self.store.get_subpoena(subpoena_id)
        if sub is None or sub.state is not SubpoenaState.AWAITING_REPLY:
            return None
        if utcnow() < sub.expires_at - timedelta(seconds=1):
            return None  # early delivery; the real timer will fire later
        ev = await self.store.get_evaluation_any(sub.evaluation_id)
        if ev is None:
            return None
        policy = await self._policy(ev)
        if sub.follow_up and sub.code_verified and sub.reply_text:
            # They answered the subpoena but not the follow-up: rule on what they said.
            return await self._admit(ev, sub, policy)
        sub.state = SubpoenaState.EXPIRED
        await self.store.put_subpoena(sub)
        await self.emit(
            ev,
            Agent.SYSTEM,
            EventType.WITNESS_AUTH,
            {"result": "NO_REPLY", "subpoena_id": sub.id, "expired_at": sub.expires_at.isoformat()},
        )
        await self.notifier.notify(ev, "subpoena.expired", {"subpoena_id": sub.id})
        decision = decide_after_testimony(
            policy=policy, auth=None, outcome=TestimonyOutcome.NO_REPLY
        )
        return await self._finalize(ev, decision, p_fraud=ev.p_fraud, rationale=decision.reason)

    async def _reply(self, sub: Subpoena, body: str) -> None:
        """Acknowledgements go out through the Bailiff's MCP tool; the courtroom holds no Twilio keys."""
        try:
            async with self.mcp.session(Agent.BAILIFF) as bailiff:
                await bailiff.call("message_witness", subpoena_id=sub.id, body=body)
        except Exception:
            log.exception("could not message witness for %s", sub.id)

    # ------------------------------------------------------------------ verdict

    async def _finalize(
        self,
        ev: Evaluation,
        decision: Decision,
        *,
        p_fraud: float | None,
        rationale: str | None,
        explain: bool = True,
    ) -> Evaluation:
        explanation: ExplanationOut | None = None
        result = None
        if explain:
            ctx = {
                "transaction": evidence.transaction_view(ev),
                "decision": decision.model_dump(mode="json"),
                "p_fraud": p_fraud,
                "findings": [
                    f.model_dump(mode="json", exclude={"source_ref"}) for f in ev.findings
                ],
                "testimony": ev.testimony.claims.model_dump() if ev.testimony else None,
                "receipt_check": ev.testimony.receipt.model_dump(
                    mode="json", include={"result", "merchant", "amount", "date", "reasons"}
                )
                if ev.testimony and ev.testimony.receipt
                else None,
            }
            try:
                result = await self.llm.generate(
                    Agent.STENOGRAPHER, prompts.STENOGRAPHER, ctx, ExplanationOut
                )
                explanation = result.value
            except LlmError as exc:
                log.warning("stenographer failed: %s", exc)
        now = utcnow()
        ev = await self._save(
            ev,
            status=decision.status,
            verdict=decision.verdict,
            p_fraud=p_fraud,
            rationale=rationale or decision.reason,
            explanation=explanation.bank_explanation if explanation else decision.reason,
            ruled_at=now,
        )
        await self.emit(
            ev,
            Agent.STENOGRAPHER if explanation else Agent.SYSTEM,
            EventType.VERDICT,
            {
                "verdict": decision.verdict,
                "status": decision.status,
                "outcome": decision.outcome,
                "reason": decision.reason,
                "reissue_card": decision.reissue_card,
                "p_fraud": p_fraud,
                **(explanation.model_dump() if explanation else {}),
            },
            result=result,
        )
        event_type = (
            "evaluation.escalated"
            if decision.status is EvaluationStatus.ESCALATED
            else "evaluation.completed"
        )
        await self.notifier.notify(
            ev,
            event_type,
            {
                "verdict": decision.verdict,
                "status": decision.status,
                "p_fraud": p_fraud,
                "explanation": ev.explanation,
                "reissue_card": decision.reissue_card,
            },
        )
        # Stare decisis: the ruling joins this workspace's precedent library.
        precedent = precedent_for(ev)
        if precedent is not None:
            try:
                await self.store.put_precedent(precedent)
            except Exception:  # never fail a verdict over the library
                log.exception("could not record precedent for %s", ev.evaluation_id)
        return ev


def _follow_up_asks(sub: Subpoena, claims: TestimonyClaims) -> list[str]:
    """What the first reply left open; nothing once the one follow-up has been asked."""
    if sub.follow_up is not None or claims.confirms_transaction is False:
        return []
    asks = []
    if claims.confirms_transaction is None:
        asks.append("confirm")
    elif not claims.stated_reason:
        asks.append("reason")
    if sub.scam_check and claims.told_to_pay is None:
        asks.append("scam")
    return asks


def _baseline_view(b: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "home",
        "avg_amount",
        "p95_amount",
        "txn_per_day",
        "active_hours",
        "common_mccs",
        "known_devices",
        "utc_offset_hours",
    )
    return {k: b.get(k) for k in keys}


def _lookup_view(lookup: dict[str, Any]) -> dict[str, Any]:
    return {
        k: lookup.get(k)
        for k in (
            "line_type",
            "carrier",
            "last_sim_swap",
            "sim_swap_checked",
            "recent_sim_swap",
            "source",
        )
    }

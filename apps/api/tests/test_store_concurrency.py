from __future__ import annotations

import asyncio

from apitest import TEST_STORE, Env
from subpoena_schemas import Agent, EventType, PipelineEvent, utcnow
from subpoena_store import IdempotencyRecord


def test_concurrent_events_get_unique_contiguous_sequences(env: Env) -> None:
    store = env.services.store

    async def run() -> list[int]:
        events = [
            PipelineEvent(
                evaluation_id="eval_x", sequence=0, from_agent=Agent.GEO, type=EventType.FINDING
            )
            for _ in range(5)  # five expert witnesses run in parallel
        ]
        stored = await asyncio.gather(*(store.append_event(e) for e in events))
        listed = await store.list_events("eval_x")
        assert [e.sequence for e in listed] == list(range(5))
        return [e.sequence for e in stored]

    seqs = env.client.portal.call(run)  # type: ignore[union-attr]
    assert sorted(seqs) == list(range(5))


def test_concurrent_idempotency_claims_have_one_winner(env: Env) -> None:
    store = env.services.store

    async def run() -> list[IdempotencyRecord | None]:
        def rec() -> IdempotencyRecord:
            return IdempotencyRecord(env.workspace_id, "same-key", "h", utcnow())

        return list(await asyncio.gather(*(store.claim_idempotency(rec()) for _ in range(5))))

    results = env.client.portal.call(run)  # type: ignore[union-attr]
    assert sum(r is None for r in results) == 1


def test_two_store_instances_never_reuse_a_sequence(env: Env) -> None:
    """Simulates the API and the courtroom (separate processes) writing to one case."""
    if TEST_STORE != "firestore":
        return
    from subpoena_store.firestore import FirestoreStore

    first = env.services.store

    async def run() -> list[int]:
        second = FirestoreStore(first._db)  # type: ignore[attr-defined]
        e = PipelineEvent(
            evaluation_id="eval_y", sequence=0, from_agent=Agent.SYSTEM, type=EventType.CASE_OPENED
        )
        await first.append_event(e)  # warms first's cache at next=1
        await second.append_event(e)  # takes 1
        await first.append_event(e)  # cached 1 clashes -> must move to 2
        return [x.sequence for x in await first.list_events("eval_y")]

    assert env.client.portal.call(run) == [0, 1, 2]  # type: ignore[union-attr]

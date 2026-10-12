"""The same contract for every Store backend. Firestore runs when the emulator is available."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest

from subpoena_schemas import (
    Agent,
    Channel,
    DeliveryStatus,
    EventType,
    MessageDirection,
    PipelineEvent,
    Policy,
    Subpoena,
    SubpoenaState,
    WitnessMessage,
    utcnow,
)
from subpoena_store import MemoryStore, Store, Verification


def memory() -> Store:
    return MemoryStore()


def firestore_store() -> Store:
    from google.cloud import firestore

    from subpoena_store.firestore import FirestoreStore

    return FirestoreStore(firestore.AsyncClient(project=f"test-{uuid.uuid4().hex[:12]}"))


BACKENDS = [pytest.param(memory, id="memory")]
if os.environ.get("FIRESTORE_EMULATOR_HOST"):
    BACKENDS.append(pytest.param(firestore_store, id="firestore"))


@pytest.mark.parametrize("make", BACKENDS)
def test_subpoenas_messages_verifications(make: Callable[[], Store]) -> None:
    async def go() -> None:
        store = make()
        now = utcnow()

        def sub(i: int, state: SubpoenaState, minutes_ago: int) -> Subpoena:
            return Subpoena(
                id=f"sbp_{i}",
                workspace_id="ws",
                evaluation_id=f"eval_{i}",
                user_id="u",
                phone="+14155550123",
                question="q",
                channel=Channel.SMS,
                state=state,
                sent_at=now - timedelta(minutes=minutes_ago),
                expires_at=now + timedelta(minutes=15),
            )

        await store.put_subpoena(sub(1, SubpoenaState.AWAITING_REPLY, 10))
        await store.put_subpoena(sub(2, SubpoenaState.AWAITING_REPLY, 1))
        await store.put_subpoena(sub(3, SubpoenaState.ADMITTED, 0))
        open_ = await store.find_open_subpoena("+14155550123")
        assert open_ is not None and open_.id == "sbp_2"
        assert await store.find_open_subpoena("+10000000000") is None
        assert [s.id for s in await store.list_subpoenas("ws", 10)] == ["sbp_3", "sbp_2", "sbp_1"]

        for i, d in enumerate([MessageDirection.OUTBOUND, MessageDirection.INBOUND]):
            await store.put_message(
                WitnessMessage(
                    phone="+14155550123",
                    direction=d,
                    channel=Channel.SMS,
                    body=f"m{i}",
                    sid=f"SM{i}",
                    created_at=now + timedelta(seconds=i),
                )
            )
        await store.update_message_status("SM0", "READ")
        msgs = await store.list_messages("+14155550123")
        assert [m.body for m in msgs] == ["m0", "m1"] and msgs[0].status is DeliveryStatus.READ

        await store.put_verification(Verification("+1415", "h", now + timedelta(minutes=5)))
        v = await store.get_verification("+1415")
        assert v is not None and v.code_hash == "h"
        await store.delete_verification("+1415")
        assert await store.get_verification("+1415") is None

        await store.put_policy(Policy(workspace_id="ws", version=1))
        await store.put_policy(Policy(workspace_id="ws", version=2))
        assert [p.version for p in await store.list_policies("ws")] == [2, 1]
        active = await store.get_active_policy("ws")
        assert active is not None and active.version == 2

        for _ in range(3):
            await store.append_event(
                PipelineEvent(
                    evaluation_id="e", sequence=0, from_agent=Agent.SYSTEM, type=EventType.ERROR
                )
            )
        assert [e.sequence for e in await store.list_events("e", after_sequence=0)] == [1, 2]

    asyncio.run(go())


@pytest.mark.parametrize("make", BACKENDS)
def test_members_and_audit(make: Callable[[], Store]) -> None:
    from subpoena_schemas import Actor, ActorType, AuditEntry, Member, Role

    async def go() -> None:
        store = make()
        a = Member(workspace_id="ws_a", email="ana@bank.test", role=Role.ADMIN)
        b = Member(workspace_id="ws_b", email="ana@bank.test")
        c = Member(workspace_id="ws_a", email="cy@bank.test")
        for m in (a, b, c):
            await store.put_member(m)
        assert [m.id for m in await store.list_members("ws_a")] == [a.id, c.id]
        assert {m.workspace_id for m in await store.find_members_by_email("ANA@bank.test")} == {
            "ws_a",
            "ws_b",
        }
        assert await store.get_member("ws_b", a.id) is None  # scoped to its workspace
        await store.delete_member("ws_b", c.id)  # wrong workspace: no-op
        await store.delete_member("ws_a", c.id)
        assert [m.id for m in await store.list_members("ws_a")] == [a.id]

        actor = Actor(type=ActorType.MEMBER, id=a.id, name=a.email)
        t0 = utcnow()
        for i in range(3):
            await store.append_audit(
                AuditEntry(
                    workspace_id="ws_a",
                    actor=actor,
                    action=f"test.{i}",
                    at=t0 + timedelta(seconds=i),
                    after={"i": i},
                )
            )
        await store.append_audit(AuditEntry(workspace_id="ws_b", actor=actor, action="other"))
        rows = await store.list_audit("ws_a", limit=2)
        assert [r.action for r in rows] == ["test.2", "test.1"]
        assert rows[0].after == {"i": 2}

    asyncio.run(go())

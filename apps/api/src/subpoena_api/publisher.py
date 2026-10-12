"""Hand-off to the courtroom over Pub/Sub.

Topics: ``evaluations.created`` (new ambiguous case) and ``subpoena.activity`` (witness reply
or code arrived). Messages carry identifiers only; the courtroom reads state from the store.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

from subpoena_schemas import Evaluation

TOPIC_EVALUATIONS_CREATED = "evaluations.created"
TOPIC_SUBPOENA_ACTIVITY = "subpoena.activity"
log = logging.getLogger(__name__)


def message_for(ev: Evaluation) -> dict[str, Any]:
    return {"evaluation_id": ev.evaluation_id, "workspace_id": ev.workspace_id}


class Publisher(Protocol):
    async def publish_evaluation_created(self, ev: Evaluation) -> None: ...
    async def publish_subpoena_activity(self, subpoena_id: str) -> None: ...


class MemoryPublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []

    async def publish_evaluation_created(self, ev: Evaluation) -> None:
        self.messages.append((TOPIC_EVALUATIONS_CREATED, message_for(ev)))

    async def publish_subpoena_activity(self, subpoena_id: str) -> None:
        self.messages.append((TOPIC_SUBPOENA_ACTIVITY, {"subpoena_id": subpoena_id}))


class LogPublisher:
    async def publish_evaluation_created(self, ev: Evaluation) -> None:
        log.info("publish %s %s", TOPIC_EVALUATIONS_CREATED, json.dumps(message_for(ev)))

    async def publish_subpoena_activity(self, subpoena_id: str) -> None:
        log.info("publish %s %s", TOPIC_SUBPOENA_ACTIVITY, subpoena_id)


class PubSubPublisher:
    def __init__(
        self,
        project_id: str,
        topic: str = TOPIC_EVALUATIONS_CREATED,
        activity_topic: str = TOPIC_SUBPOENA_ACTIVITY,
    ) -> None:
        from google.cloud import pubsub_v1  # type: ignore[attr-defined]

        self._client = pubsub_v1.PublisherClient()
        self._topic = self._client.topic_path(project_id, topic)
        self._activity = self._client.topic_path(project_id, activity_topic)

    async def _publish(self, topic: str, data: dict[str, Any], **attrs: str) -> None:
        future = self._client.publish(topic, json.dumps(data).encode(), **attrs)
        await asyncio.wrap_future(future)

    async def publish_evaluation_created(self, ev: Evaluation) -> None:
        await self._publish(self._topic, message_for(ev), kind="evaluation.created")

    async def publish_subpoena_activity(self, subpoena_id: str) -> None:
        await self._publish(self._activity, {"subpoena_id": subpoena_id}, kind="subpoena.activity")

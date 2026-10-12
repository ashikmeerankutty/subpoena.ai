"""Subpoena timeouts: an asyncio timer locally, Cloud Tasks in the cloud (Spec §3 Pause/Resume)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from subpoena_schemas import utcnow


class Scheduler(Protocol):
    async def schedule_timeout(self, subpoena_id: str, at: datetime) -> None: ...


class LocalScheduler:
    def __init__(self, on_timeout: Callable[[str], Awaitable[object]] | None = None) -> None:
        self.on_timeout = on_timeout
        self.scheduled: dict[str, datetime] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def schedule_timeout(self, subpoena_id: str, at: datetime) -> None:
        self.scheduled[subpoena_id] = at

        async def fire() -> None:
            await asyncio.sleep(max(0.0, (at - utcnow()).total_seconds()))
            if self.on_timeout:
                await self.on_timeout(subpoena_id)

        task = asyncio.create_task(fire())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


class CloudTasksScheduler:
    """HTTP task to the courtroom's ``/tasks/subpoena-timeout``, authenticated with OIDC."""

    def __init__(
        self, project: str, location: str, queue: str, target_url: str, service_account: str
    ) -> None:
        from google.cloud import tasks_v2

        self._tasks_v2 = tasks_v2
        self._client = tasks_v2.CloudTasksAsyncClient()
        self._queue = self._client.queue_path(project, location, queue)
        self._url = target_url
        self._sa = service_account

    async def schedule_timeout(self, subpoena_id: str, at: datetime) -> None:
        from google.protobuf import timestamp_pb2

        ts = timestamp_pb2.Timestamp()
        ts.FromDatetime(at)
        tv2 = self._tasks_v2
        task = tv2.Task(
            schedule_time=ts,
            http_request=tv2.HttpRequest(
                http_method=tv2.HttpMethod.POST,
                url=self._url,
                headers={"Content-Type": "application/json"},
                body=json.dumps({"subpoena_id": subpoena_id}).encode(),
                oidc_token=tv2.OidcToken(
                    service_account_email=self._sa, audience=self._url.rsplit("/tasks", 1)[0]
                ),
            ),
        )
        await self._client.create_task(parent=self._queue, task=task)

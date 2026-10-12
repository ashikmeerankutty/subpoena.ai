"""Outbound bank webhooks (Spec §8): ``Subpoena-Signature: t=..,v1=HMAC_SHA256(secret, t.body)``.

Each workspace's signing secret is derived from the master secret, so it can be shown in the
Console (Sources) and rotated by rotating the master. Deliveries retry with backoff.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from subpoena_schemas import Evaluation, new_id, utcnow

log = logging.getLogger(__name__)
BACKOFF_SECONDS = (0, 2, 10)


def workspace_secret(master: str, workspace_id: str) -> str:
    return (
        "whsec_" + hmac.new(master.encode(), workspace_id.encode(), hashlib.sha256).hexdigest()[:40]
    )


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    t = timestamp or int(time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t = int(parts.get("t", "0"))
    if abs(time.time() - t) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, body, t), header)


class BankNotifier:
    def __init__(self, master_secret: str, http: httpx.AsyncClient | None = None) -> None:
        self._master = master_secret
        self._http = http
        self.sent: list[dict[str, Any]] = []  # recent deliveries, for tests and the local console

    async def notify(self, ev: Evaluation, event_type: str, data: dict[str, Any]) -> None:
        url = ev.options.callback_url
        payload = {
            "id": new_id("evt"),
            "type": event_type,
            "created_at": utcnow().isoformat(),
            "data": {
                "evaluation_id": ev.evaluation_id,
                "transaction_id": ev.transaction.transaction_id,
                **data,
            },
        }
        record: dict[str, Any] = {
            "url": str(url) if url else None,
            "payload": payload,
            "attempts": [],
        }
        self.sent.append(record)
        del self.sent[:-200]
        if url is None:
            return
        body = json.dumps(payload, default=str).encode()
        secret = workspace_secret(self._master, ev.workspace_id)
        http = self._http or httpx.AsyncClient(timeout=10)
        try:
            for delay in BACKOFF_SECONDS:
                await asyncio.sleep(delay)
                try:
                    r = await http.post(
                        str(url),
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "Subpoena-Signature": sign(secret, body),
                        },
                    )
                    record["attempts"].append(r.status_code)
                    if r.status_code < 300:
                        return
                except httpx.HTTPError as exc:
                    record["attempts"].append(str(exc))
            log.warning("webhook %s to %s failed after retries", event_type, url)
        finally:
            if self._http is None:
                await http.aclose()

"""Outbound bank webhooks (Spec §8): ``Subpoena-Signature: t=..,v1=HMAC_SHA256(secret, t.body)``.

Each workspace's signing secret is derived from the master secret, so it can be shown in the
Console (Sources) and rotated by rotating the master. Deliveries retry with backoff.

Every event also fans out to the workspace's Destinations (webhook, Slack, Pub/Sub, BigQuery),
concurrently, with each delivery (after retries) written to the delivery log.
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

from subpoena_schemas import (
    Delivery,
    Destination,
    DestinationDeliveryStatus,
    Evaluation,
    new_id,
    utcnow,
)
from subpoena_store import Store

from .destinations import Deliverer, DeliveryError

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


def evaluation_summary(ev: Evaluation) -> dict[str, Any]:
    return {
        "status": ev.status,
        "verdict": ev.verdict,
        "p_fraud": ev.p_fraud,
        "amount": str(ev.transaction.amount),
        "currency": ev.transaction.currency,
        "merchant": ev.transaction.merchant.name,
        "user_id": ev.transaction.user_id,
    }


class BankNotifier:
    def __init__(
        self,
        master_secret: str,
        http: httpx.AsyncClient | None = None,
        *,
        store: Store | None = None,
        console_url: str | None = None,
        project: str | None = None,
    ) -> None:
        self._master = master_secret
        self._http = http
        self.store = store  # enables Destinations
        self.deliverer = Deliverer(master_secret, console_url=console_url, project=project)
        self.backoff = BACKOFF_SECONDS
        self.sent: list[dict[str, Any]] = []  # recent deliveries, for tests and the local console

    async def notify(self, ev: Evaluation, event_type: str, data: dict[str, Any]) -> None:
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
        await asyncio.gather(self._callback(ev, payload), self._fan_out(ev, payload))

    async def _fan_out(self, ev: Evaluation, payload: dict[str, Any]) -> None:
        if self.store is None:
            return
        try:
            dests = [
                d
                for d in await self.store.list_destinations(ev.workspace_id)
                if d.wants(payload["type"])
            ]
        except Exception:  # destinations must never break a verdict
            log.exception("could not load destinations for %s", ev.workspace_id)
            return
        if dests:
            event = {
                **payload,
                "workspace_id": ev.workspace_id,
                "evaluation": evaluation_summary(ev),
            }
            await asyncio.gather(*(self.deliver(d, event) for d in dests))

    async def deliver(self, dest: Destination, event: dict[str, Any]) -> Delivery:
        """Send with retries and record the outcome in the delivery log."""
        started = time.perf_counter()
        attempts, code, error = 0, None, None
        http = self._http or httpx.AsyncClient(timeout=10)
        try:
            for delay in self.backoff:
                await asyncio.sleep(delay)
                attempts += 1
                try:
                    code = await self.deliverer.send(http, dest, event)
                    error = None
                    break
                except DeliveryError as exc:
                    code, error = exc.code, str(exc)[:500]
                    if not exc.retryable:
                        break
                except Exception as exc:  # unexpected client errors are recorded, not raised
                    code, error = None, f"{type(exc).__name__}: {exc}"[:500]
                    break
        finally:
            if self._http is None:
                await http.aclose()
        delivery = Delivery(
            workspace_id=dest.workspace_id,
            destination_id=dest.id,
            event_id=event["id"],
            event_type=event["type"],
            evaluation_id=event.get("data", {}).get("evaluation_id"),
            status=DestinationDeliveryStatus.FAILED if error else DestinationDeliveryStatus.SUCCESS,
            attempts=attempts,
            response_code=code,
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        if error:
            log.warning("delivery of %s to %s failed: %s", event["type"], dest.id, error)
        if self.store is not None:
            await self.store.append_delivery(delivery)
        return delivery

    async def _callback(self, ev: Evaluation, payload: dict[str, Any]) -> None:
        url = ev.options.callback_url
        event_type = payload["type"]
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
            for delay in self.backoff:
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

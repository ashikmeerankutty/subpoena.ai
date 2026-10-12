"""Delivery to workspace destinations: signed webhooks, Slack alerts, Pub/Sub and BigQuery.

URLs are checked when a destination is saved (https only, no private/metadata hosts) so the
service cannot be pointed at internal endpoints.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import re
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from subpoena_schemas import Destination, DestinationType

PUBSUB_TOPIC = re.compile(
    r"^projects/[a-z][-a-z0-9]{4,28}[a-z0-9]/topics/[A-Za-z][\w.~+%-]{2,254}$"
)
BQ_TABLE = re.compile(r"^[a-z][-a-z0-9]{4,28}[a-z0-9]\.\w{1,1024}\.[\w-]{1,1024}$")
BLOCKED_HOSTS = {"localhost", "metadata", "metadata.google.internal"}

# BigQuery export schema (create the table with this, see infra/gcp/deploy.sh).
BQ_SCHEMA = [
    ("event_id", "STRING"),
    ("event_type", "STRING"),
    ("created_at", "TIMESTAMP"),
    ("workspace_id", "STRING"),
    ("evaluation_id", "STRING"),
    ("transaction_id", "STRING"),
    ("status", "STRING"),
    ("verdict", "STRING"),
    ("p_fraud", "FLOAT"),
    ("amount", "NUMERIC"),
    ("currency", "STRING"),
    ("merchant", "STRING"),
    ("data", "JSON"),
]


class DeliveryError(Exception):
    def __init__(self, message: str, *, code: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def destination_secret(master: str, destination_id: str) -> str:
    return (
        "whsec_"
        + hmac.new(master.encode(), destination_id.encode(), hashlib.sha256).hexdigest()[:40]
    )


def _public_https(url: str, *, allow_local: bool) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if allow_local and parsed.scheme == "http" and host in ("localhost", "127.0.0.1"):
        return url
    if parsed.scheme != "https" or not host:
        raise ValueError("URL must be https://")
    if host in BLOCKED_HOSTS or host.endswith((".internal", ".local", ".localhost")):
        raise ValueError("URL host is not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url
    if not ip.is_global:
        raise ValueError("URL must not point to a private or reserved address")
    return url


def validate(
    dtype: DestinationType, config: dict[str, str], *, allow_local: bool = False
) -> dict[str, str]:
    """Return the normalized config for ``dtype`` or raise ``ValueError``."""
    if dtype is DestinationType.WEBHOOK:
        return {"url": _public_https(config.get("url", "").strip(), allow_local=allow_local)}
    if dtype is DestinationType.SLACK:
        url = config.get("url", "").strip()
        if not url.startswith("https://hooks.slack.com/services/"):
            raise ValueError(
                "Use a Slack incoming-webhook URL (https://hooks.slack.com/services/…)"
            )
        return {"url": url}
    if dtype is DestinationType.PUBSUB:
        topic = config.get("topic", "").strip()
        if not PUBSUB_TOPIC.match(topic):
            raise ValueError("Topic must look like projects/<project>/topics/<topic>")
        return {"topic": topic}
    table = config.get("table", "").strip()
    if not BQ_TABLE.match(table):
        raise ValueError("Table must look like <project>.<dataset>.<table>")
    return {"table": table}


def sign(secret: str, body: bytes, timestamp: int) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


EMOJI = {
    "evaluation.escalated": "⚠️",
    "evaluation.overridden": "⚖️",
    "subpoena.sent": "📨",
    "subpoena.expired": "⌛",
    "testimony.received": "🗣️",
    "witness_auth.failed": "🚫",
    "destination.test": "🧪",
}


def slack_message(event: dict[str, Any], console_url: str | None) -> dict[str, Any]:
    e = event.get("evaluation") or {}
    verdict = e.get("verdict")
    emoji = EMOJI.get(event["type"]) or {"APPROVE": "✅", "BLOCK": "⛔"}.get(str(verdict), "🔔")
    amount = f"{Decimal(str(e['amount'])):,.2f} {e.get('currency', '')}" if e.get("amount") else ""
    title = f"{emoji} *{event['type']}*" + (f" · {amount} at {e.get('merchant')}" if amount else "")
    eid = event["data"].get("evaluation_id")
    link = (
        f"<{console_url.rstrip('/')}/cases/{eid}|Open case {eid}>" if console_url and eid else eid
    )
    p = e.get("p_fraud")
    fields = [
        f"*Verdict*\n{verdict or '—'}",
        f"*Status*\n{e.get('status') or '—'}",
        f"*p_fraud*\n{'—' if p is None else f'{float(p):.2f}'}",
        f"*Reason*\n{event['data'].get('reason') or e.get('reason') or '—'}",
    ]
    return {
        "text": title,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": title}},
            {"type": "section", "fields": [{"type": "mrkdwn", "text": f} for f in fields]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Subpoena.ai · {link}"}]},
        ],
    }


def bigquery_row(event: dict[str, Any]) -> dict[str, Any]:
    e = event.get("evaluation") or {}
    return {
        "event_id": event["id"],
        "event_type": event["type"],
        "created_at": event["created_at"],
        "workspace_id": event["workspace_id"],
        "evaluation_id": event["data"].get("evaluation_id"),
        "transaction_id": event["data"].get("transaction_id"),
        "status": e.get("status"),
        "verdict": e.get("verdict"),
        "p_fraud": e.get("p_fraud"),
        "amount": e.get("amount"),
        "currency": e.get("currency"),
        "merchant": e.get("merchant"),
        "data": json.dumps(event["data"], default=str),
    }


class Deliverer:
    """Sends one event to one destination (a single attempt; the notifier retries)."""

    def __init__(
        self, master_secret: str, *, console_url: str | None = None, project: str | None = None
    ) -> None:
        self._master = master_secret
        self._console_url = console_url
        self._project = project
        self._publisher: Any = None
        self._bq: Any = None

    async def send(
        self, http: httpx.AsyncClient, dest: Destination, event: dict[str, Any]
    ) -> int | None:
        if dest.type is DestinationType.WEBHOOK:
            body = json.dumps(event, default=str).encode()
            headers = {
                "Content-Type": "application/json",
                "Subpoena-Signature": sign(
                    destination_secret(self._master, dest.id), body, int(time.time())
                ),
                "Subpoena-Event": event["type"],
            }
            return await self._post(http, dest.config["url"], content=body, headers=headers)
        if dest.type is DestinationType.SLACK:
            return await self._post(
                http, dest.config["url"], json=slack_message(event, self._console_url)
            )
        if dest.type is DestinationType.PUBSUB:
            await asyncio.to_thread(self._publish, dest.config["topic"], event)
            return None
        await asyncio.to_thread(self._insert, dest.config["table"], event)
        return None

    @staticmethod
    async def _post(http: httpx.AsyncClient, url: str, **kw: Any) -> int:
        try:
            r = await http.post(url, **kw)
        except httpx.HTTPError as exc:
            raise DeliveryError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code >= 300:
            retryable = r.status_code >= 500 or r.status_code == 429
            raise DeliveryError(f"HTTP {r.status_code}", code=r.status_code, retryable=retryable)
        return r.status_code

    def _publish(self, topic: str, event: dict[str, Any]) -> None:
        from google.api_core.exceptions import GoogleAPICallError
        from google.cloud import pubsub_v1  # type: ignore[attr-defined]

        if self._publisher is None:
            self._publisher = pubsub_v1.PublisherClient()
        try:
            self._publisher.publish(
                topic,
                json.dumps(event, default=str).encode(),
                event_type=event["type"],
                workspace_id=event["workspace_id"],
            ).result(timeout=30)
        except GoogleAPICallError as exc:
            raise DeliveryError(str(exc), code=exc.code, retryable=False) from exc

    def _insert(self, table: str, event: dict[str, Any]) -> None:
        from google.api_core.exceptions import GoogleAPICallError
        from google.cloud.bigquery import Client

        if self._bq is None:
            self._bq = Client(project=self._project)
        try:
            errors = self._bq.insert_rows_json(table, [bigquery_row(event)], row_ids=[event["id"]])
        except GoogleAPICallError as exc:
            raise DeliveryError(str(exc), code=exc.code, retryable=False) from exc
        if errors:
            raise DeliveryError(f"BigQuery rejected the row: {errors}", retryable=False)

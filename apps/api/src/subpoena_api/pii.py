"""PII masking for VIEWER principals (Spec §10: "PII is masked for viewers").

Applied to every JSON and server-sent-event response after authentication has decided the
caller is a viewer in a workspace with masking on, so new endpoints are covered by default.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

PHONE = re.compile(r"\+\d{5,13}(\d{2})\b")
IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3})\.\d{1,3}\.\d{1,3}\b")
EMAIL = re.compile(
    r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b"
)
MASKED_TYPES = ("application/json", "application/problem+json", "text/event-stream")


def mask_text(text: str) -> str:
    text = PHONE.sub(r"+•••••••\1", text)
    text = IPV4.sub(r"\1.•.•", text)
    return EMAIL.sub(r"\1•••@\2", text)


class MaskPiiMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start: Message | None = None
        masking = False

        async def wrapped(message: Message) -> None:
            nonlocal start, masking
            if message["type"] == "http.response.start":
                ctype = dict(message.get("headers", [])).get(b"content-type", b"").decode()
                state: dict[str, Any] = scope.get("state", {})
                masking = bool(state.get("mask_pii")) and ctype.startswith(MASKED_TYPES)
                if not masking:
                    await send(message)
                    return
                start = message  # held until the body length is known
                return
            if message["type"] == "http.response.body" and masking:
                body = mask_text(message.get("body", b"").decode()).encode()
                if start is not None:
                    headers = [(k, v) for k, v in start["headers"] if k != b"content-length"]
                    if not message.get("more_body", False):
                        headers.append((b"content-length", str(len(body)).encode()))
                    await send({**start, "headers": headers})
                    start = None
                await send({**message, "body": body})
                return
            await send(message)

        await self.app(scope, receive, wrapped)

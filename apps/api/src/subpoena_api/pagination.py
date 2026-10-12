"""Opaque cursor tokens for ``?limit=&page_token=`` pagination."""

from __future__ import annotations

import base64
import json

from .problems import ProblemError


def encode_cursor(created_at_iso: str, item_id: str) -> str:
    raw = json.dumps([created_at_iso, item_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        created_at, item_id = json.loads(raw)
        if not isinstance(created_at, str) or not isinstance(item_id, str):
            raise ValueError
        return created_at, item_id
    except (ValueError, TypeError) as exc:
        raise ProblemError(400, "invalid-page-token", "page_token is malformed") from exc

"""API key generation and hashing. Only the HMAC of a secret is ever stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX_LEN = 12


def generate_secret(mode: str) -> str:
    return f"sk_{mode}_{secrets.token_urlsafe(24)}"


def hash_secret(secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), secret.encode(), hashlib.sha256).hexdigest()


def display_prefix(secret: str) -> str:
    return secret[:PREFIX_LEN]

"""Approximate Vertex AI list prices (USD per 1M tokens) for cost-per-case accounting."""

from __future__ import annotations

from collections.abc import Iterable

from subpoena_schemas import PipelineEvent

PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}
DEFAULT = PRICES["gemini-2.5-flash"]


def cost(events: Iterable[PipelineEvent]) -> tuple[float, int]:
    usd, tokens = 0.0, 0
    for e in events:
        if e.tokens is None or not e.model or e.model == "scripted":
            continue
        price_in, price_out = PRICES.get(e.model, DEFAULT)
        usd += (e.tokens.input * price_in + e.tokens.output * price_out) / 1_000_000
        tokens += e.tokens.input + e.tokens.output
    return round(usd, 5), tokens

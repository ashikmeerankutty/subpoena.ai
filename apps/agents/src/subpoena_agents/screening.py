"""Testimony screening (Spec §6): Model Armor, with a local heuristic fallback.

Screening never blocks the witness from being heard: a flagged reply is still converted to
structured claims by the tool-less extractor, but its raw text is withheld from the Judge and
the case cannot be auto-approved on it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules|prompts?)",
    r"disregard (all |the )?(previous|prior|above)",
    r"\b(system|developer) (prompt|message|instructions?)\b",
    r"you are (now )?(a|an|the) ",
    r"\bp_fraud\b",
    r"\b(set|change|make) (the )?(verdict|decision|score|probability)",
    r"\b(approve|unblock) (this|the|my) (transaction|payment) (now|immediately)",
    r"</?\s*(untrusted|system|assistant|tool)\s*>",
    r"\bjailbreak\b|\bDAN\b",
]
URL = re.compile(r"https?://|www\.", re.I)


@dataclass
class ScreeningResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)
    engine: str = "heuristic"


class Screener(Protocol):
    async def screen(self, text: str) -> ScreeningResult: ...


class HeuristicScreener:
    async def screen(self, text: str) -> ScreeningResult:
        reasons = []
        if any(re.search(p, text, re.I) for p in INJECTION_PATTERNS):
            reasons.append("prompt_injection")
        if URL.search(text):
            reasons.append("url")
        return ScreeningResult(flagged=bool(reasons), reasons=reasons)


class ModelArmorScreener:
    """``templates.sanitizeUserPrompt``; falls back to the heuristic if the call fails."""

    def __init__(self, template: str, location: str) -> None:
        self._template = template
        self._url = (
            f"https://modelarmor.{location}.rep.googleapis.com/v1/{template}:sanitizeUserPrompt"
        )
        self._fallback = HeuristicScreener()

    async def screen(self, text: str) -> ScreeningResult:
        try:
            import google.auth
            import google.auth.transport.requests

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())  # type: ignore[no-untyped-call]
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.post(
                    self._url,
                    headers={"Authorization": f"Bearer {creds.token}"},
                    json={"userPromptData": {"text": text}},
                )
                r.raise_for_status()
                result = r.json()["sanitizationResult"]
        except Exception as exc:
            log.warning("Model Armor unavailable, using heuristic screening: %s", exc)
            return await self._fallback.screen(text)
        reasons = [name for name, f in result.get("filterResults", {}).items() if _matched(f)]
        heuristic = await self._fallback.screen(text)
        flagged = result.get("filterMatchState") == "MATCH_FOUND" or heuristic.flagged
        return ScreeningResult(
            flagged=flagged, reasons=sorted(set(reasons + heuristic.reasons)), engine="model_armor"
        )


def _matched(node: object) -> bool:
    if isinstance(node, dict):
        if node.get("matchState") == "MATCH_FOUND":
            return True
        return any(_matched(v) for v in node.values())
    return False

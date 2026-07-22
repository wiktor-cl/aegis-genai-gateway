"""Prompt-injection screening — heuristic pattern matching on the inbound
request text (see docs/threat-model.md, STRIDE: Tampering via prompt
injection).

This is deliberately a pattern-matching allowlist-of-red-flags, not an LLM
classifier: zero cost, zero latency added beyond a handful of regex scans,
fully offline, and its false-negative rate (novel phrasings it doesn't
recognize) is an explicit, documented limitation rather than a hidden one.
A production deployment with budget would likely add an LLM-based classifier
as a second layer on top of this, not instead of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (all |any )?(previous|above|prior) instructions", re.IGNORECASE),
    re.compile(r"disregard (all |any )?(previous|above|prior) (instructions|rules)", re.IGNORECASE),
    re.compile(r"reveal (your |the )?(system prompt|hidden instructions)", re.IGNORECASE),
    re.compile(r"do anything now|jailbreak|\bDAN mode\b", re.IGNORECASE),
    re.compile(r"pretend (you have|to be) no (restrictions|rules|guidelines)", re.IGNORECASE),
    re.compile(r"you are no longer (bound by|restricted by)", re.IGNORECASE),
    re.compile(r"</?(system|instructions)>", re.IGNORECASE),
    re.compile(r"override (your |the )?(safety|content) (policy|guidelines)", re.IGNORECASE),
]


@dataclass
class InjectionHit:
    pattern: str
    match: str


def screen_for_injection(text: str) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            hits.append(InjectionHit(pattern=pattern.pattern, match=m.group()))
    return hits

"""PII detection and redaction — runs on outbound requests before any
provider sees them (see docs/threat-model.md, "confidential data leaves the
organization through the request body regardless of provider routing").

Regex-based, not ML-based: deterministic, offline, and auditable — a
reviewer can read every pattern here and know exactly what it does and does
not catch. The known trade-off is recall: this will not catch PII in every
possible format (see the module docstring in threat-model.md's guardrails
section for the explicit limitation).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
_CREDIT_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_SSN_LIKE_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

_ENTITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": _EMAIL_RE,
    "phone": _PHONE_RE,
    "credit_card": _CREDIT_CARD_RE,
    "ssn_like": _SSN_LIKE_RE,
}


@dataclass
class PiiHit:
    entity: str
    match: str
    start: int
    end: int


def _luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def find_pii(text: str, entities: list[str]) -> list[PiiHit]:
    hits: list[PiiHit] = []
    for entity in entities:
        pattern = _ENTITY_PATTERNS.get(entity)
        if pattern is None:
            continue
        for m in pattern.finditer(text):
            if entity == "credit_card":
                digits = re.sub(r"[ -]", "", m.group())
                if not _luhn_valid(digits):
                    continue  # Luhn check cuts false positives on 13-19 digit runs
            hits.append(PiiHit(entity=entity, match=m.group(), start=m.start(), end=m.end()))
    return hits


def redact(text: str, hits: list[PiiHit]) -> str:
    result = text
    for hit in sorted(hits, key=lambda h: h.start, reverse=True):
        placeholder = f"[REDACTED_{hit.entity.upper()}]"
        result = result[: hit.start] + placeholder + result[hit.end :]
    return result

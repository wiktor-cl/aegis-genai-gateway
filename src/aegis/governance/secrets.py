"""Secret-leak detection — runs on outbound responses before they reach the
caller (see docs/threat-model.md: a provider or a tool's HTTP/SQL result
could echo back a credential that ended up in context; this is the last
line of defense before it leaves Aegis).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "generic_api_key_assignment": re.compile(
        r"\b(api[_-]?key|secret|token)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{20,}[\"']?", re.IGNORECASE
    ),
    "jwt_like": re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
}


@dataclass
class SecretHit:
    kind: str
    match: str


def find_secrets(text: str) -> list[SecretHit]:
    hits: list[SecretHit] = []
    for kind, pattern in _SECRET_PATTERNS.items():
        m = pattern.search(text)
        if m:
            hits.append(SecretHit(kind=kind, match=m.group()))
    return hits

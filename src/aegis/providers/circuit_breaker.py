"""Per-provider circuit breaker used by the router (ADR-0002) for failover.

CLOSED -> (N consecutive failures) -> OPEN -> (after reset_timeout) -> HALF_OPEN
  -> (1 success) -> CLOSED
  -> (1 failure) -> OPEN, timer restarts

Deliberately in-memory and per-process: Aegis runs the gateway as a small
number of stateless replicas behind a load balancer, and a slightly slower
convergence of "is this provider healthy" per replica is an acceptable
trade-off for not adding a shared-state dependency to the hot path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the breaker is OPEN."""


@dataclass
class _BreakerEntry:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0


class CircuitBreakerRegistry:
    def __init__(self, failure_threshold: int = 5, reset_timeout_s: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout_s = reset_timeout_s
        self._entries: dict[str, _BreakerEntry] = {}

    def _entry(self, provider_name: str) -> _BreakerEntry:
        return self._entries.setdefault(provider_name, _BreakerEntry())

    def before_call(self, provider_name: str) -> None:
        entry = self._entry(provider_name)
        if entry.state == CircuitState.OPEN:
            if time.monotonic() - entry.opened_at >= self._reset_timeout_s:
                entry.state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError(f"circuit open for provider '{provider_name}'")

    def on_success(self, provider_name: str) -> None:
        entry = self._entry(provider_name)
        entry.state = CircuitState.CLOSED
        entry.consecutive_failures = 0

    def on_failure(self, provider_name: str) -> None:
        entry = self._entry(provider_name)
        entry.consecutive_failures += 1
        tripped = entry.consecutive_failures >= self._failure_threshold
        if entry.state == CircuitState.HALF_OPEN or tripped:
            entry.state = CircuitState.OPEN
            entry.opened_at = time.monotonic()

    def state_of(self, provider_name: str) -> CircuitState:
        return self._entry(provider_name).state

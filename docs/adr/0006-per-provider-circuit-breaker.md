# ADR-0006: Per-provider circuit breaker instead of a single retry loop

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

ADR-0002 gives the router an ordered candidate list per request and a failover mechanism.
The naive failover implementation is "on error, just try the next candidate, every time" — no
memory of past failures. That has a specific, well-known failure mode: if a provider is fully
down (outage, expired credentials, region issue), *every single request* that lists it as a
candidate pays the full latency of a failed attempt before failing over, for as long as the
outage lasts. At any meaningful request volume that both wastes latency budget on doomed calls
and can amplify load against a struggling provider (retry storms).

## Decyzja

Each provider has its own circuit breaker (`aegis.providers.circuit_breaker.CircuitBreakerRegistry`),
independent of the others: CLOSED (normal) → OPEN after N consecutive failures (skips the
provider entirely until a reset timeout elapses) → HALF_OPEN (one probe attempt) → CLOSED on
success or back to OPEN on failure. The router checks `before_call()` before ever invoking a
candidate and records `on_success`/`on_failure` after — a provider with an open circuit is
skipped without a network call at all, moving straight to the next candidate.

## Konsekwencje

### Pozytywne
- After the failure threshold trips, subsequent requests stop paying the latency cost of a
  known-broken provider — they fail over immediately to the next candidate (or to `local`,
  which given the routing policy's structure is usually the last, always-available fallback).
- Bounded blast radius: one provider's outage degrades to "always route around it," not
  "every request now takes provider-timeout-seconds longer."
- In-memory and per-process by design (see the module docstring) — no additional shared-state
  dependency (e.g. Redis) on the hot path, an explicit trade-off for simplicity at this scale.

### Negatywne / koszty
- Per-process state means a fleet of N replicas converges on "provider X is down" independently
  and at slightly different times — acceptable for a small number of stateless replicas, but a
  real inconsistency if the fleet grows large enough that the convergence lag matters.
- A fixed `reset_timeout_s` is a blunt instrument: too short and a still-broken provider gets
  hammered by probes; too long and a recovered provider stays needlessly avoided. No adaptive
  backoff (e.g. exponential reset timeout growth) is implemented.

### Neutralne / do obserwacji
- If Aegis ever runs enough replicas for the per-process inconsistency to matter, the natural
  evolution is a shared breaker state in Redis (already in the stack for rate limiting/cache) —
  not a redesign of the breaker's state machine itself.

## Odrzucone alternatywy

### Plain retry-on-failure with no memory (try every candidate, every time)
Simplest possible failover. Rejected: pays full failure latency on every request during an
extended outage, with no mechanism to "learn" that a candidate is currently unhealthy.

### Shared (Redis-backed) circuit breaker state from day one
Would solve the per-process convergence gap immediately. Rejected for now: adds a dependency on
the hot path (every provider call would need a Redis round-trip to check/update breaker state)
for a benefit (multi-replica consistency) that doesn't matter at this project's actual scale —
premature for a portfolio-scale deployment; see `docs/cost-model.md` for the assumed scale.

### Health-check polling instead of failure-triggered breaking
An alternative design continuously polls each provider's `health_check()` on a timer and routes
around unhealthy ones proactively. Rejected as the primary mechanism: it adds constant
background traffic to providers (cost-relevant for cloud providers, even if simulated here) to
detect a failure mode that reactive breaking already catches on the first real request — though
`health_check()` still exists on `LLMProvider` and is a reasonable input to a future readiness
probe, it is not wired into routing decisions today.

## Powiązane

- [[0002-policy-based-routing]]
- `src/aegis/providers/circuit_breaker.py`, `src/aegis/providers/router.py`
- `docs/runbook.md` — manual failover procedure during an extended provider outage

"""Prometheus metrics, wired at the same interface boundary as tracing: the
provider router (per-provider latency, tokens) and the agent runtime
(guardrail hits, cost — guardrail hits recorded starting Sprint 3).
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry()

PROVIDER_LATENCY_SECONDS = Histogram(
    "aegis_provider_latency_seconds",
    "Latency of a single provider chat call attempt",
    ["provider", "outcome"],
    registry=REGISTRY,
)
PROVIDER_TOKENS_TOTAL = Counter(
    "aegis_provider_tokens_total",
    "Tokens consumed per provider call",
    ["provider", "direction"],
    registry=REGISTRY,
)
GUARDRAIL_HITS_TOTAL = Counter(
    "aegis_guardrail_hits_total",
    "Number of times a guardrail rule triggered",
    ["rule"],
    registry=REGISTRY,
)
ESTIMATED_COST_USD_TOTAL = Counter(
    "aegis_estimated_cost_usd_total",
    "Simulated cost accrued (cloud providers are never actually billed here)",
    ["provider", "tenant_id"],
    registry=REGISTRY,
)


def render_latest() -> bytes:
    return generate_latest(REGISTRY)

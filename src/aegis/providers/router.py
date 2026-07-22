"""Policy-based provider router (ADR-0002).

Loads `policies/routing.yaml`, picks an ordered list of candidate providers
for a request based on its `RoutingContext` (data classification, cost tier),
and executes with per-provider circuit breaking and failover. Application
code never picks a provider directly — it always goes through `route()`.
"""

from __future__ import annotations

import time
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from aegis.observability.metrics import PROVIDER_LATENCY_SECONDS, PROVIDER_TOKENS_TOTAL
from aegis.observability.tracing import get_tracer
from aegis.providers.base import (
    ChatRequest,
    ChatResponse,
    LLMProvider,
    ProviderAuthError,
    ProviderError,
)
from aegis.providers.circuit_breaker import CircuitBreakerRegistry, CircuitOpenError

_tracer = get_tracer(__name__)

DataClassification = str  # "public" | "internal" | "confidential" | "restricted"


class RoutingContext(BaseModel):
    tenant_id: str
    data_classification: DataClassification = "internal"
    cost_tier: str = "standard"


class ProviderConfig(BaseModel):
    model: str
    region: str
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float


class RoutingRule(BaseModel):
    name: str
    when: dict[str, list[str]]
    allow: list[str]

    def matches(self, context: RoutingContext) -> bool:
        ctx = context.model_dump()
        for key, allowed_values in self.when.items():
            if ctx.get(key) not in allowed_values:
                return False
        return True


class FailoverConfig(BaseModel):
    max_attempts: int = 3
    failure_threshold: int = 5
    reset_timeout_s: float = 30.0

    @field_validator("max_attempts")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_attempts must be >= 1")
        return v


class RoutingPolicy(BaseModel):
    version: int
    default_provider: str
    providers: dict[str, ProviderConfig]
    rules: list[RoutingRule]
    failover: FailoverConfig

    @classmethod
    def from_yaml(cls, path: Path | str) -> RoutingPolicy:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        failover_raw = raw.get("failover", {})
        flat_failover = {
            "max_attempts": failover_raw.get("max_attempts", 3),
            **failover_raw.get("circuit_breaker", {}),
        }
        return cls(
            version=raw["version"],
            default_provider=raw["default_provider"],
            providers=raw["providers"],
            rules=raw["rules"],
            failover=FailoverConfig(**flat_failover),
        )

    def candidates_for(self, context: RoutingContext) -> list[str]:
        for rule in self.rules:
            if rule.matches(context):
                return rule.allow
        return [self.default_provider]


class NoHealthyProviderError(ProviderError):
    """All candidate providers for this request failed or had an open circuit."""


class ProviderRouter:
    def __init__(
        self,
        policy: RoutingPolicy,
        providers: dict[str, LLMProvider],
        breaker_registry: CircuitBreakerRegistry | None = None,
    ) -> None:
        self._policy = policy
        self._providers = providers
        self._breakers = breaker_registry or CircuitBreakerRegistry(
            failure_threshold=policy.failover.failure_threshold,
            reset_timeout_s=policy.failover.reset_timeout_s,
        )

    @classmethod
    def from_yaml(
        cls, path: Path | str, providers: dict[str, LLMProvider]
    ) -> ProviderRouter:
        return cls(RoutingPolicy.from_yaml(path), providers)

    def candidates_for(self, context: RoutingContext) -> list[str]:
        return self._policy.candidates_for(context)

    async def route(self, request: ChatRequest, context: RoutingContext) -> ChatResponse:
        candidates = self.candidates_for(context)[: self._policy.failover.max_attempts]
        if not candidates:
            raise NoHealthyProviderError("routing policy produced zero candidate providers")

        last_error: Exception | None = None
        for provider_name in candidates:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue
            try:
                self._breakers.before_call(provider_name)
            except CircuitOpenError as exc:
                last_error = exc
                continue

            model = self._policy.providers[provider_name].model
            provider_request = request.model_copy(update={"model": request.model or model})
            started = time.monotonic()
            with _tracer.start_as_current_span(
                "provider.chat",
                attributes={
                    "aegis.provider": provider_name,
                    "aegis.request_id": request.request_id,
                    "aegis.tenant_id": request.tenant_id,
                },
            ) as span:
                try:
                    response = await provider.chat(provider_request)
                except ProviderAuthError:
                    self._observe(provider_name, started, "auth_error")
                    span.set_attribute("aegis.outcome", "auth_error")
                    raise  # not retryable, not a transient/failover-able condition
                except ProviderError as exc:
                    self._breakers.on_failure(provider_name)
                    self._observe(provider_name, started, "error")
                    span.set_attribute("aegis.outcome", "error")
                    last_error = exc
                    continue

                span.set_attribute("aegis.outcome", "success")
                span.set_attribute("aegis.input_tokens", response.usage.input_tokens)
                span.set_attribute("aegis.output_tokens", response.usage.output_tokens)

            self._observe(provider_name, started, "success", response)
            self._breakers.on_success(provider_name)
            return response

        raise NoHealthyProviderError(
            f"no healthy provider among candidates {candidates}"
        ) from last_error

    @staticmethod
    def _observe(
        provider_name: str,
        started: float,
        outcome: str,
        response: ChatResponse | None = None,
    ) -> None:
        PROVIDER_LATENCY_SECONDS.labels(provider=provider_name, outcome=outcome).observe(
            time.monotonic() - started
        )
        if response is not None:
            PROVIDER_TOKENS_TOTAL.labels(provider=provider_name, direction="input").inc(
                response.usage.input_tokens
            )
            PROVIDER_TOKENS_TOTAL.labels(provider=provider_name, direction="output").inc(
                response.usage.output_tokens
            )

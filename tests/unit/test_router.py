from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from aegis.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    LLMProvider,
    ProviderAuthError,
    ProviderUnavailableError,
    Role,
    StreamChunk,
    Usage,
)
from aegis.providers.router import (
    NoHealthyProviderError,
    ProviderRouter,
    RoutingContext,
    RoutingPolicy,
)

ROUTING_YAML = Path(__file__).resolve().parents[2] / "policies" / "routing.yaml"


class FakeProvider(LLMProvider):
    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self._error = error
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return ChatResponse(
            message=ChatMessage(role=Role.ASSISTANT, content=f"reply from {self.name}"),
            usage=Usage(input_tokens=1, output_tokens=1),
            provider_name=self.name,
            model=request.model,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="")

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise NotImplementedError

    async def health_check(self) -> bool:
        return self._error is None


def _request(model: str = "") -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role=Role.USER, content="hi")],
        model=model,
        tenant_id="t-1",
        request_id="r-1",
    )


def test_policy_loads_from_yaml_and_validates() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    assert policy.default_provider == "local"
    assert set(policy.providers) == {"local", "bedrock", "foundry"}
    assert policy.failover.max_attempts == 3


def test_confidential_data_only_ever_candidates_local() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    ctx = RoutingContext(tenant_id="t-1", data_classification="confidential")
    assert policy.candidates_for(ctx) == ["local"]

    ctx_restricted = RoutingContext(tenant_id="t-1", data_classification="restricted")
    assert policy.candidates_for(ctx_restricted) == ["local"]


def test_public_premium_prefers_cloud_candidates() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    ctx = RoutingContext(tenant_id="t-1", data_classification="public", cost_tier="premium")
    assert policy.candidates_for(ctx) == ["bedrock", "foundry", "local"]


async def test_router_returns_first_healthy_candidate() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    local = FakeProvider("local")
    bedrock = FakeProvider("bedrock")
    router = ProviderRouter(policy, providers={"local": local, "bedrock": bedrock})

    ctx = RoutingContext(tenant_id="t-1", data_classification="confidential")
    response = await router.route(_request(), ctx)

    assert response.provider_name == "local"
    assert bedrock.call_count == 0


async def test_router_fails_over_to_next_candidate_on_transient_error() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    bedrock = FakeProvider("bedrock", error=ProviderUnavailableError("throttled"))
    foundry = FakeProvider("foundry")
    local = FakeProvider("local")
    providers = {"bedrock": bedrock, "foundry": foundry, "local": local}
    router = ProviderRouter(policy, providers=providers)

    ctx = RoutingContext(tenant_id="t-1", data_classification="public", cost_tier="premium")
    response = await router.route(_request(), ctx)

    assert response.provider_name == "foundry"
    assert bedrock.call_count == 1


async def test_router_does_not_fail_over_on_auth_error() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    bedrock = FakeProvider("bedrock", error=ProviderAuthError("bad credentials"))
    foundry = FakeProvider("foundry")
    providers = {"bedrock": bedrock, "foundry": foundry, "local": FakeProvider("local")}
    router = ProviderRouter(policy, providers=providers)

    ctx = RoutingContext(tenant_id="t-1", data_classification="public", cost_tier="premium")
    with pytest.raises(ProviderAuthError):
        await router.route(_request(), ctx)

    assert foundry.call_count == 0


async def test_router_raises_when_all_candidates_exhausted() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    failing = {
        name: FakeProvider(name, error=ProviderUnavailableError("down"))
        for name in ("bedrock", "foundry", "local")
    }
    router = ProviderRouter(policy, providers=failing)

    ctx = RoutingContext(tenant_id="t-1", data_classification="public", cost_tier="premium")
    with pytest.raises(NoHealthyProviderError):
        await router.route(_request(), ctx)


async def test_router_skips_provider_with_open_circuit() -> None:
    policy = RoutingPolicy.from_yaml(ROUTING_YAML)
    bedrock = FakeProvider("bedrock")
    foundry = FakeProvider("foundry")
    providers = {"bedrock": bedrock, "foundry": foundry, "local": FakeProvider("local")}
    router = ProviderRouter(policy, providers=providers)
    for _ in range(policy.failover.failure_threshold):
        router._breakers.on_failure("bedrock")

    ctx = RoutingContext(tenant_id="t-1", data_classification="public", cost_tier="premium")
    response = await router.route(_request(), ctx)

    assert response.provider_name == "foundry"
    assert bedrock.call_count == 0

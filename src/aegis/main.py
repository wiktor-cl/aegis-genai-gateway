"""FastAPI application entrypoint.

Wires config -> providers -> policy router -> API routes. Only `LocalProvider`
is ever actually called (see docs/adr/0001-provider-abstraction-layer.md);
BedrockProvider/FoundryProvider are constructed here (cheap — their SDK
clients are built lazily on first call) so the router can route to them if
someone runs this outside of the zero-cost constraints of this repository,
but nothing in this codebase's tests or docker-compose stack exercises that
path against a real account.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from aegis.api.routes_admin import router as admin_router
from aegis.api.routes_agent import router as agent_router
from aegis.api.routes_chat import router as chat_router
from aegis.api.routes_cost import router as cost_router
from aegis.config import settings
from aegis.cost.pricing import PricingTable
from aegis.governance.pipeline import GuardrailPipeline
from aegis.governance.policies import GuardrailPolicySet
from aegis.observability.metrics import render_latest
from aegis.observability.tracing import configure_tracing
from aegis.providers.bedrock_provider import BedrockProvider
from aegis.providers.foundry_provider import FoundryProvider
from aegis.providers.local_provider import LocalProvider
from aegis.providers.router import ProviderRouter
from aegis.tenancy.models import TenantRegistry


def build_router() -> ProviderRouter:
    providers = {
        "local": LocalProvider(base_url=settings.ollama_base_url),
        "bedrock": BedrockProvider(region_name=settings.aws_region),
        "foundry": FoundryProvider(
            endpoint=settings.azure_ai_foundry_endpoint,
            api_version=settings.azure_openai_api_version,
        ),
    }
    return ProviderRouter.from_yaml(settings.routing_policy_path, providers)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_tracing()
    app.state.provider_router = build_router()
    app.state.guardrails = GuardrailPipeline(
        GuardrailPolicySet.from_yaml(settings.guardrails_policy_path)
    )
    app.state.pricing = PricingTable.from_yaml(settings.pricing_policy_path)
    app.state.tenants = TenantRegistry.from_yaml(settings.tenants_policy_path)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Aegis", version="0.1.0", lifespan=lifespan)
    app.include_router(chat_router)
    app.include_router(agent_router)
    app.include_router(cost_router)
    app.include_router(admin_router)

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=render_latest(), media_type="text/plain; version=0.0.4")

    return app


app = create_app()

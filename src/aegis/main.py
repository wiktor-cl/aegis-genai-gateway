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

from fastapi import FastAPI

from aegis.api.routes_chat import router as chat_router
from aegis.config import settings
from aegis.providers.bedrock_provider import BedrockProvider
from aegis.providers.foundry_provider import FoundryProvider
from aegis.providers.local_provider import LocalProvider
from aegis.providers.router import ProviderRouter


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
    app.state.provider_router = build_router()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Aegis", version="0.1.0", lifespan=lifespan)
    app.include_router(chat_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()

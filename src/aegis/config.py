"""Runtime configuration, loaded from environment variables only.

No secret ever has a default value that looks like a real credential — see
.env.example for the full list of variables docker-compose/CI expect.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AEGIS_", env_file=".env", extra="ignore")

    environment: str = "local"

    # Postgres (audit, cost, evaluations)
    database_url: str = "postgresql+asyncpg://aegis:aegis@localhost:5432/aegis"

    # Redis (queue, rate limiting, cache)
    redis_url: str = "redis://localhost:6379/0"

    # Local provider (Ollama) — the only provider actually called
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Cloud providers — never called with these in this repo; present only so
    # the code is deployable as-is by a team with a real account. Contract
    # tests inject fakes and never read these values.
    aws_region: str = "us-east-1"
    azure_ai_foundry_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"

    routing_policy_path: Path = REPO_ROOT / "policies" / "routing.yaml"
    guardrails_policy_path: Path = REPO_ROOT / "policies" / "guardrails.yaml"
    pricing_policy_path: Path = REPO_ROOT / "policies" / "pricing.yaml"
    tenants_policy_path: Path = REPO_ROOT / "policies" / "tenants.yaml"

    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "aegis-gateway"

    jwt_signing_key: str = "dev-only-not-a-secret-change-in-env"
    jwt_algorithm: str = "HS256"


settings = Settings()

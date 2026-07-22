"""Loads policies/pricing.yaml and computes a simulated cost per call.

Deliberately separate from policies/routing.yaml: routing.yaml answers
"which provider" (ADR-0002), this answers "what would it have cost" — the
two overlap in that both mention providers/models, but the pricing table is
the single source of truth for $ figures, so cost math never has to guess
which of two conflicting numbers is authoritative.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ModelPricing(BaseModel):
    input_per_1k_usd: float
    output_per_1k_usd: float


class PricingTable(BaseModel):
    version: int
    default_currency: str = "USD"
    providers: dict[str, dict[str, ModelPricing]]
    fallback: ModelPricing

    @classmethod
    def from_yaml(cls, path: Path | str) -> PricingTable:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            version=raw["version"],
            default_currency=raw.get("default_currency", "USD"),
            providers=raw["providers"],
            fallback=raw["fallback"],
        )

    def price_for(self, provider: str, model: str) -> ModelPricing:
        return self.providers.get(provider, {}).get(model, self.fallback)

    def estimate_cost_usd(
        self, provider: str, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        pricing = self.price_for(provider, model)
        return (input_tokens / 1000) * pricing.input_per_1k_usd + (
            output_tokens / 1000
        ) * pricing.output_per_1k_usd

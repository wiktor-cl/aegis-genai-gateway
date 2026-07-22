from pathlib import Path

from aegis.cost.pricing import PricingTable

PRICING_YAML = Path(__file__).resolve().parents[2] / "policies" / "pricing.yaml"


def test_local_provider_is_free() -> None:
    table = PricingTable.from_yaml(PRICING_YAML)
    cost = table.estimate_cost_usd(
        "local", "llama3.1:8b", input_tokens=10_000, output_tokens=5_000
    )
    assert cost == 0.0


def test_bedrock_cost_matches_rate_card() -> None:
    table = PricingTable.from_yaml(PRICING_YAML)
    cost = table.estimate_cost_usd(
        "bedrock",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        input_tokens=1000,
        output_tokens=1000,
    )
    assert cost == 0.003 + 0.015


def test_unknown_model_falls_back_to_fallback_pricing() -> None:
    table = PricingTable.from_yaml(PRICING_YAML)
    cost = table.estimate_cost_usd(
        "bedrock", "some-future-model", input_tokens=1000, output_tokens=1000
    )
    assert cost == 0.0  # fallback in pricing.yaml is zero

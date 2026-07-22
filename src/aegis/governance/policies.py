"""Loads and validates policies/guardrails.yaml (ADR-0002's YAML-policy
pattern applied to guardrails: a security-relevant rule change is a config
edit + review, not a code change + redeploy).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class PiiConfig(BaseModel):
    enabled: bool = True
    action: str = "redact"
    """redact | block"""
    entities: list[str] = Field(default_factory=list)


class PromptInjectionConfig(BaseModel):
    enabled: bool = True
    action: str = "block"


class OutputValidationConfig(BaseModel):
    enabled: bool = True


class SecretLeakConfig(BaseModel):
    enabled: bool = True
    action: str = "block"


class TenantGuardrailPolicy(BaseModel):
    pii: PiiConfig
    prompt_injection: PromptInjectionConfig
    max_input_chars: int = 20_000
    output_validation: OutputValidationConfig
    secret_leak: SecretLeakConfig


class GuardrailPolicySet(BaseModel):
    version: int
    default_tenant_policy: str
    tenants: dict[str, TenantGuardrailPolicy]

    @classmethod
    def from_yaml(cls, path: Path | str) -> GuardrailPolicySet:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            version=raw["version"],
            default_tenant_policy=raw["default_tenant_policy"],
            tenants=raw["tenants"],
        )

    def for_policy_name(self, policy_name: str | None) -> TenantGuardrailPolicy:
        name = policy_name or self.default_tenant_policy
        return self.tenants.get(name, self.tenants[self.default_tenant_policy])

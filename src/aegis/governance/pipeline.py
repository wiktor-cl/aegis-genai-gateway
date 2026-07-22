"""Ties the individual guardrail checks together into one pre/post pass.

Called around every provider call — from the chat API route and from
`AgentRuntime` (see docs/adr — guardrails wired once, at the same interface
boundary as observability, per ADR-0001's design principle). Every hit,
whether it results in a redaction or a block, is meant to be handed to
`AuditStore.record()` by the caller — this module only decides what happens
to the text, not how it's logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aegis.governance.pii import find_pii, redact
from aegis.governance.policies import GuardrailPolicySet, TenantGuardrailPolicy
from aegis.governance.prompt_injection import screen_for_injection
from aegis.governance.secrets import find_secrets


@dataclass
class GuardrailHit:
    rule: str
    action: str
    detail: list[str] = field(default_factory=list)


@dataclass
class GuardrailResult:
    allowed: bool
    text: str
    hits: list[GuardrailHit] = field(default_factory=list)
    block_reason: str | None = None


class GuardrailPipeline:
    def __init__(self, policy_set: GuardrailPolicySet) -> None:
        self._policies = policy_set

    def _policy_for(self, policy_name: str | None) -> TenantGuardrailPolicy:
        return self._policies.for_policy_name(policy_name)

    def screen_request(self, text: str, policy_name: str | None = None) -> GuardrailResult:
        policy = self._policy_for(policy_name)
        hits: list[GuardrailHit] = []

        if len(text) > policy.max_input_chars:
            return GuardrailResult(
                allowed=False,
                text=text,
                hits=[GuardrailHit(rule="max_input_chars", action="block")],
                block_reason=f"input exceeds max_input_chars ({policy.max_input_chars})",
            )

        if policy.prompt_injection.enabled:
            injection_hits = screen_for_injection(text)
            if injection_hits:
                hits.append(
                    GuardrailHit(
                        rule="prompt_injection",
                        action=policy.prompt_injection.action,
                        detail=[h.match for h in injection_hits],
                    )
                )
                if policy.prompt_injection.action == "block":
                    return GuardrailResult(
                        allowed=False,
                        text=text,
                        hits=hits,
                        block_reason="prompt injection detected",
                    )

        working_text = text
        if policy.pii.enabled:
            pii_hits = find_pii(working_text, policy.pii.entities)
            if pii_hits:
                hits.append(
                    GuardrailHit(
                        rule="pii", action=policy.pii.action, detail=[h.entity for h in pii_hits]
                    )
                )
                if policy.pii.action == "block":
                    return GuardrailResult(
                        allowed=False, text=text, hits=hits, block_reason="PII detected in input"
                    )
                working_text = redact(working_text, pii_hits)

        return GuardrailResult(allowed=True, text=working_text, hits=hits)

    def screen_response(self, text: str, policy_name: str | None = None) -> GuardrailResult:
        policy = self._policy_for(policy_name)
        hits: list[GuardrailHit] = []

        if policy.secret_leak.enabled:
            secret_hits = find_secrets(text)
            if secret_hits:
                hits.append(
                    GuardrailHit(
                        rule="secret_leak",
                        action=policy.secret_leak.action,
                        detail=[h.kind for h in secret_hits],
                    )
                )
                if policy.secret_leak.action == "block":
                    return GuardrailResult(
                        allowed=False,
                        text=text,
                        hits=hits,
                        block_reason="secret leak detected in output",
                    )

        return GuardrailResult(allowed=True, text=text, hits=hits)

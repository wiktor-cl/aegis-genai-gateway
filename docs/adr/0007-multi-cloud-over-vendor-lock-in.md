# ADR-0007: Multi-cloud provider support instead of committing to one vendor

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

An enterprise adopting Aegis is very likely already committed elsewhere to either AWS or Azure
(or both, across business units) for reasons entirely unrelated to GenAI — existing contracts,
compliance certifications already obtained on one cloud, data residency agreements, security
review cycles already invested in one vendor's IAM model. A gateway that only spoke to one
cloud's model service would force the organization to either accept a second, uncontrolled
integration path for teams standardized on the other cloud, or delay adoption entirely pending
a cross-cloud negotiation. Separately, model quality/pricing/availability shifts fast enough
(new model releases, deprecations, regional rollouts) that a single-vendor commitment risks
being stuck mid-migration exactly when a policy or cost change makes leaving desirable.

## Decyzja

Aegis integrates with AWS Bedrock and Azure AI Foundry as peers, both behind the same
`LLMProvider` interface (ADR-0001), selectable per request by policy (ADR-0002), with neither
treated as "the real one" and the other as an afterthought: both have full contract-test
coverage (ADR-0003), both are represented in the Terraform/Bicep IaC (Sprint 4), and the
routing policy schema has no special-casing for either.

## Konsekwencje

### Pozytywne
- An organization standardized on either cloud (or both, in different business units) can adopt
  Aegis without a forced migration or a "second, shadow gateway" for the other cloud's teams.
- Negotiating leverage: because switching cost between Bedrock and Foundry is "edit
  `policies/routing.yaml`," not "rewrite application code," the organization is not structurally
  locked into whichever vendor's pricing or terms happen to be in effect when Aegis is adopted.
- Forces the provider abstraction (ADR-0001) to be honest about what's actually common across
  providers versus AWS/Azure-specific — a single-cloud design could hide provider-specific
  assumptions in the interface without anyone noticing.

### Negatywne / koszty
- Real, ongoing cost: two SDKs, two sets of error-code mappings (`_AUTH_ERROR_CODES`/
  `_RETRYABLE_ERROR_CODES` for Bedrock vs. `openai.AuthenticationError`/`RateLimitError` for
  Foundry), two IaC modules to keep current as each cloud's services evolve. A single-cloud
  project would have half this surface area to maintain.
- Feature parity is not guaranteed and not assumed: a capability unique to one provider (a
  Bedrock-specific guardrail, an Azure-specific content filter) either needs a lowest-common-
  denominator treatment or provider-specific extension fields (see ADR-0001's "Negative
  consequences" on this exact trade-off) — multi-cloud support does not mean identical
  capability everywhere.
- Testing burden doubles for anything provider-facing (contract tests, fixtures) compared to
  supporting one vendor.

### Neutralne / do obserwacji
- The two cloud providers implemented are the two large enterprise GenAI platforms as of this
  writing; adding a third (e.g. Google Vertex AI) is a new `LLMProvider` implementation plus
  contract tests, not an architecture change — the multi-cloud decision generalizes to
  "provider-agnostic," it doesn't hard-code "exactly two clouds."

## Odrzucone alternatywy

### Single-cloud (pick AWS Bedrock or Azure AI Foundry, integrate deeply)
Would halve integration/maintenance/testing surface and allow deeper use of that one platform's
native features without lowest-common-denominator compromises. Rejected because it reintroduces
exactly the vendor lock-in the product's premise (per README's product context) is meant to
prevent — an enterprise gateway that only works with one cloud is not centrally solving the
"every team integrates differently" problem, it is relocating it to "every team not on that
cloud integrates around Aegis instead of through it."

### Multi-cloud via a third-party abstraction library instead of a bespoke `LLMProvider` interface
Would reduce the code Aegis itself has to maintain. Rejected for the same reason given in
ADR-0001's rejected alternatives: it moves architecturally significant decisions (what the
common request/response shape is, how errors are classified) into a dependency this project
does not control, which is a worse trade for a project whose purpose includes demonstrating
those exact design decisions.

## Powiązane

- [[0001-provider-abstraction-layer]]
- [[0003-local-first-contract-testing]]
- `infra/terraform/` (AWS), `infra/bicep/` (Azure)

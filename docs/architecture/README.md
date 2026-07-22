# Architecture — C4 diagrams

Three levels, each linking to the next:

1. [**context.md**](context.md) — who/what talks to Aegis (developers, operators, Ollama,
   Bedrock/Foundry, OpenTelemetry).
2. [**container.md**](container.md) — the deployable pieces from `docker-compose.yml` (Console,
   API, Postgres, Redis) and how they connect.
3. [**component.md**](component.md) — inside the API container, by actual Python package under
   `src/aegis/`.

All three are Mermaid, rendered and checked with `@mermaid-js/mermaid-cli` before being
committed (a flowchart with a typo doesn't fail CI the way a code change would, so it's
verified by hand at authoring time — see the note in each file: solid vs. dashed arrows
distinguish "actually called in this repo" from "implemented but only contract-tested," per
[ADR-0003](../adr/0003-local-first-contract-testing.md)).

See also: [docs/threat-model.md](../threat-model.md) (STRIDE), [docs/cost-model.md](../cost-model.md),
[docs/runbook.md](../runbook.md), and the ADRs in [docs/adr/](../adr/) for the "why" behind each
of these boxes and arrows.

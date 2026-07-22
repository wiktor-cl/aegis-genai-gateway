# Aegis

Enterprise multi-cloud GenAI agent gateway and runtime — one API for every team, security and
cost policy enforced centrally, model providers swappable without touching application code.

> **Portfolio project.** Built to demonstrate GenAI solution architecture: provider
> abstraction, policy-based routing, agent runtime, guardrails, cost control, multi-tenancy,
> an evaluation gate wired into CI, observability, and reviewable (never deployed) multi-cloud
> IaC. See `docs/` for architecture (C4), 10 ADRs, threat model, cost model, and a runbook.

## Zero-cost, local-first — read this before you run anything

**This project never calls a paid API and never provisions a cloud resource.**

- The only provider actually invoked over the network, anywhere in this repo (tests,
  docker-compose, CI), is `LocalProvider`, talking to a local Ollama instance. No API key, no
  egress, no bill.
- `BedrockProvider` (AWS Bedrock, via `boto3`) and `FoundryProvider` (Azure AI Foundry / Azure
  OpenAI, via the `openai` + `azure-identity` SDKs) are **fully implemented, production-shaped
  code** — but in this repository they are exercised exclusively by **contract tests** against
  recorded fixtures and fakes implementing the same client interface
  (`tests/contract/`). They are never invoked against a real AWS/Azure account here. See
  [ADR-0003](docs/adr/0003-local-first-contract-testing.md).
- IaC (`infra/terraform` for AWS, `infra/bicep` for Azure) is validated **statically only** —
  `terraform validate` / `tflint` / `checkov` / `bicep build`. `terraform apply` and
  `az deployment create` are never run, and CI has no cloud credentials to run them with.
- Nothing here is a claim of production deployment. It is a claim of reviewable, tested,
  deployable-as-is code — verified as far as that can be verified for free.

## Run it (3 commands)

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health
```

This starts Postgres, Redis, a local Ollama instance, and the Aegis API — fully offline, no
cloud credentials anywhere in the stack (see `docker-compose.yml`).

## Architecture at a glance

```mermaid
flowchart LR
    Team[Team / application] -->|"one API"| Gateway[Aegis Gateway]
    Gateway --> Guardrails[Governance & guardrails]
    Gateway --> Router[Policy router]
    Router -->|"default, zero-cost"| Local[LocalProvider\n(Ollama)]
    Router -.->|"contract-tested only"| Bedrock[BedrockProvider\n(AWS Bedrock)]
    Router -.->|"contract-tested only"| Foundry[FoundryProvider\n(Azure AI Foundry)]
    Gateway --> Audit[(Postgres: audit, cost, evals)]
    Gateway --> Cache[(Redis: queue, rate limit, cache)]
    Gateway --> Otel[OpenTelemetry / Prometheus]
```

Full C4 diagrams (context, container, component) live in `docs/architecture/`.

## Why it's built this way

Every non-obvious architectural decision has an ADR in `docs/adr/`, including why there's a
provider abstraction layer instead of direct SDK calls per team, why routing is YAML policy
instead of a fixed model choice, why cloud integrations are contract-tested instead of live,
why evaluation is a CI gate instead of a dashboard nobody checks, and multi-cloud vs. vendor
lock-in. Read [ADR-0001](docs/adr/0001-provider-abstraction-layer.md) first.

## Status

Built in 4 sprints; this README and `docs/` are updated as each sprint lands.

- [x] **Sprint 1** — Provider abstraction layer (`LLMProvider`), `LocalProvider` /
      `BedrockProvider` / `FoundryProvider`, YAML policy router with per-provider circuit
      breaking and failover, contract tests against recorded fixtures, docker-compose.
- [x] **Sprint 2** — Agent runtime (tool-calling loop, step/token budgets, retries, full run
      trace with deterministic replay), 4 tools (knowledge base search, calculator, read-only
      SQL, allowlisted HTTP with SSRF guards), Postgres-backed trace storage with Alembic
      migrations, OpenTelemetry tracing + Prometheus metrics on the provider router.
- [x] **Sprint 3** — Governance & guardrails (PII redaction with Luhn-checked credit cards,
      prompt-injection screening, secret-leak blocking, per-tenant YAML policies), append-only
      audit log, cost tracking + monthly budget enforcement (soft alert / hard stop), and
      multi-tenancy/RBAC (Argon2-hashed API keys with rotation, roles enforced at the DB query
      layer — see ADR-0005) wired into both API entry points.
- [ ] **Sprint 4** — Evaluation harness wired into CI as a merge gate, React console, IaC
      (Terraform/Bicep, statically validated), full architecture documentation.

## Repository layout

```
src/aegis/          FastAPI app, provider layer, agent runtime, governance, cost, tenancy
console/            React + TypeScript + Tailwind operator console
policies/           YAML policy: routing, guardrails, pricing, tenants
infra/terraform/    AWS IaC (Bedrock, IAM, VPC endpoints, Secrets Manager) — validated, not applied
infra/bicep/        Azure IaC (AI Foundry, Key Vault, Private Endpoint, Managed Identity) — same
tests/unit/         Fast, no external dependencies
tests/integration/  Testcontainers-backed (Postgres, Redis)
tests/contract/     Provider contract tests against recorded fixtures — never live
docs/adr/           Architecture Decision Records
docs/architecture/  C4 diagrams (Mermaid)
```

## Development

```bash
python -m venv .venv && .venv\Scripts\activate   # or: source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/unit tests/contract
ruff check src tests
mypy src
```

## License

MIT

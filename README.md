# Aegis

[![CI](https://github.com/wiktor-cl/aegis-genai-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/wiktor-cl/aegis-genai-gateway/actions/workflows/ci.yml)

Enterprise multi-cloud GenAI agent gateway and runtime — one API for every team, security and
cost policy enforced centrally, model providers swappable without touching application code.

## What it actually does

Two C4 views (the full set, including the component diagram, lives in
[`docs/architecture/`](docs/architecture/)) and a real trace, captured by actually running the
agent loop against a live local model — not hand-written, not simulated.

**Who/what talks to Aegis:**

```mermaid
flowchart TB
    Developer["Developer / team\n[Person]"] -->|"HTTPS, API key"| Aegis
    Operator["Operator / admin\n[Person]"] -->|"HTTPS, via the Console"| Aegis
    Aegis["Aegis Gateway\n[Software System]"] -->|"only path actually\ncalled at runtime"| Ollama["Ollama\n[local]"]
    Aegis -.->|"contract-tested only\n— never live here"| Bedrock["AWS Bedrock"]
    Aegis -.->|"contract-tested only\n— never live here"| Foundry["Azure AI Foundry"]

    style Bedrock stroke-dasharray: 5 5
    style Foundry stroke-dasharray: 5 5
```

**What's actually deployed** (`docker-compose.yml`):

```mermaid
flowchart TB
    Console["Console\nReact + TS + Tailwind"] -->|"HTTPS + API key"| API["API\nFastAPI, Python 3.12"]
    API -->|"asyncpg"| Postgres[("Postgres\nruns, audit, cost, keys")]
    API -.->|"provisioned, not yet\nwired up — see D1 in\ndocs/threat-model.md"| Redis[("Redis")]
    API -->|"/api/chat"| Ollama["Ollama"]

    style Redis stroke-dasharray: 5 5
```

**A real trace** — `GET /v1/agents/runs/{id}`, captured from an actual `docker compose up` +
`ollama pull llama3.1:8b` + `POST /v1/agents/run` call (trimmed of Ollama's raw response
envelope for length; nothing here is hand-typed):

```json
{
  "run_id": "07d84de3-4cd9-4cda-bde7-eefe1094bc25",
  "status": "completed",
  "final_output": "The result of 6 * 7 is 42.",
  "total_input_tokens": 531,
  "total_output_tokens": 32,
  "steps": [
    {
      "step_type": "llm_call",
      "provider_name": "local", "model": "llama3.1:8b",
      "output": { "tool_calls": [
        { "id": "call_wechav2j", "name": "calculator", "arguments": { "expression": "6 * 7" } }
      ] },
      "input_tokens": 434, "output_tokens": 19, "duration_ms": 16621
    },
    {
      "step_type": "tool_call",
      "tool_name": "calculator",
      "input": { "expression": "6 * 7" },
      "output": { "result": "42" },
      "duration_ms": 0
    },
    {
      "step_type": "llm_call",
      "provider_name": "local", "model": "llama3.1:8b",
      "output": { "message": { "content": "The result of 6 * 7 is 42." } },
      "input_tokens": 97, "output_tokens": 13, "duration_ms": 2820
    }
  ]
}
```

The Console renders exactly this response as a step-by-step trace viewer:

![Aegis Console — agent run trace view](docs/img/console-run-trace.png)

> **Portfolio project.** Built to demonstrate GenAI solution architecture: provider
> abstraction, policy-based routing, agent runtime, guardrails, cost control, multi-tenancy,
> an evaluation gate wired into CI, observability, and reviewable (never deployed) multi-cloud
> IaC. See `docs/` for architecture (C4), 8 ADRs, threat model, cost model, and a runbook.

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

## Prerequisites

| Tool | Minimum version | Needed for |
|---|---|---|
| [Docker Engine](https://docs.docker.com/engine/install/) + Compose V2 | 24.0+ (the `docker compose` plugin, not the standalone `docker-compose` v1 script — `docker-compose.yml` uses the plain Compose Specification, no `version:` key) | `docker compose up` — the API, Postgres, Redis, Ollama |
| [Python](https://www.python.org/downloads/) | 3.12+ (`pyproject.toml`'s `requires-python`) | Running `scripts/seed.py`/`scripts/smoke_test_local_provider.py` locally, or hacking on `src/aegis` outside Docker |
| [Node.js](https://nodejs.org/) | 22+ (pinned in `.github/workflows/ci.yml`'s `console` job) | `console/` — `npm install && npm run dev` |

Nothing else — no cloud CLI, no cloud account, no API key. See "Zero-cost, local-first" above.

## Run it

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health

# first run only — creates the schema (migrations are a deliberate separate
# step, not baked into the image's CMD, so scaling to multiple API replicas
# never races migrations against each other)
docker compose exec api alembic upgrade head

# bootstrap the first admin API key — every other key is minted through the
# API itself, which needs an admin key to call; this is the one bootstrap
# exception (see scripts/seed.py). Needs the aegis package importable, hence
# the local install first (a throwaway venv is fine — this runs on the host,
# not in a container, because it talks to Postgres on localhost:5432).
python -m venv .venv && .venv\Scripts\activate   # or: source .venv/bin/activate
pip install -e .
AEGIS_DATABASE_URL=postgresql+asyncpg://aegis:aegis@localhost:5432/aegis \
    python scripts/seed.py --tenant-id acme-support --role admin
```

`acme-support` is one of two example tenants predefined in `policies/tenants.yaml` (the other,
`acme-legal`, uses the stricter `legal_hold` guardrail policy — see
[ADR-0002](docs/adr/0002-policy-based-routing.md)).

This starts Postgres, Redis, a local Ollama instance, and the Aegis API — fully offline, no
cloud credentials anywhere in the stack (see `docker-compose.yml`). The operator console
(`console/`) is a separate `npm run dev` step — see `console/README.md`.

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
- [x] **Sprint 4** — Evaluation harness (58 golden-fixture cases, `eval/cases/`) wired into CI
      as a merge gate (see [ADR-0008](docs/adr/0008-eval-gate-golden-fixtures.md)), operator
      console (`console/`, React + TypeScript + Tailwind: dashboard, agent runs + trace viewer,
      admin API keys), IaC (`infra/terraform` for AWS, `infra/bicep` for Azure, both statically
      validated in CI — `terraform validate`/`tflint`/`checkov` and `bicep build`/`bicep lint`),
      and full architecture documentation (`docs/architecture/` C4 diagrams, `docs/cost-model.md`,
      `docs/runbook.md`; `docs/threat-model.md` already existed from Sprint 3).

## Repository layout

```
src/aegis/          FastAPI app, provider layer, agent runtime, governance, cost, tenancy
console/            React + TypeScript + Tailwind operator console
eval/               Eval-gate: 58 golden-fixture cases run as a CI merge gate (ADR-0008)
scripts/            seed.py (bootstrap admin key), smoke_test_local_provider.py (live Ollama check)
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
ruff check src tests scripts
mypy src scripts
```

## License

MIT

# C4 — Level 2: Containers

What's inside the "Aegis Gateway" box from [context.md](context.md), and how the pieces
actually deployed by `docker-compose.yml` talk to each other. See [component.md](component.md)
for what's inside the API container.

```mermaid
flowchart TB
    Developer["Developer / team\n[Person]"]
    Operator["Operator / admin\n[Person]"]

    subgraph AegisSystem["Aegis Gateway"]
        Console["Console\n[Container: React 19 + TS + Tailwind, Vite]\nDashboard, agent runs + trace\nviewer, admin API key management"]
        API["API\n[Container: FastAPI + Uvicorn, Python 3.12]\nProvider router, agent runtime,\nguardrails, cost tracking, RBAC"]
        Postgres["Postgres\n[Container: postgres:16-alpine]\nagent_runs/steps, audit_log,\ncost_entries, api_keys"]
        Redis["Redis\n[Container: redis:7-alpine]\nProvisioned for rate limiting/queue/\ncache — NOT wired up yet, see\ndocs/threat-model.md D1"]
    end

    Ollama["Ollama\n[External Container]"]
    Bedrock["AWS Bedrock\n[External — contract-tested only]"]
    Foundry["Azure AI Foundry\n[External — contract-tested only]"]
    Otel["OpenTelemetry / Prometheus\n[External]"]

    Developer -->|"HTTPS + API key"| API
    Operator -->|"HTTPS"| Console
    Console -->|"HTTPS + API key\n(dev: Vite proxy /api/*)"| API

    API -->|"asyncpg, SQLAlchemy async"| Postgres
    API -.->|"provisioned, not yet called\nfrom application code"| Redis
    API -->|"HTTP /api/chat, /api/embeddings"| Ollama
    API -.->|"contract-tested only — ADR-0003"| Bedrock
    API -.->|"contract-tested only — ADR-0003"| Foundry
    API -->|"OTLP traces, /metrics scrape"| Otel

    style Redis stroke-dasharray: 5 5
    style Bedrock stroke-dasharray: 5 5
    style Foundry stroke-dasharray: 5 5
```

## Notes

- **Console → API** is the only path the console has — there is no separate console backend,
  no direct console→Postgres access, consistent with
  [ADR-0005](../adr/0005-rbac-enforced-at-query-layer.md): every access goes through the same
  RBAC-enforcing API layer regardless of caller.
- **Redis is deployed but not yet used** by any application code path (`src/aegis/` has no
  Redis client calls — only `config.py` defines `redis_url`). This is a known, documented gap
  (`docs/threat-model.md`, D1), not an oversight in this diagram.
- **Migrations are a separate step**, not part of the API container's startup (`docker compose
  exec api alembic upgrade head`) — see the root README's "Run it" section and
  [runbook.md](../runbook.md) for why (avoiding a migration race if the API ever scales to
  multiple replicas).

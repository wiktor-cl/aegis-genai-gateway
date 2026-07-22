# C4 — Level 1: System Context

Who and what talks to Aegis, and what Aegis itself talks to. See
[container.md](container.md) for what's inside the "Aegis Gateway" box.

```mermaid
flowchart TB
    subgraph People
        Developer["Developer / team\n[Person]\nCalls the API to build an\nAI-powered feature"]
        Operator["Operator / admin\n[Person]\nManages tenants, API keys,\nwatches cost & runs via the console"]
    end

    Aegis["Aegis Gateway\n[Software System]\nOne API for every team — policy\nrouting, guardrails, cost control,\nmulti-tenancy, agent runtime"]

    Ollama["Ollama\n[External System — local]\nThe only model backend actually\ncalled at runtime in this repo"]
    Bedrock["AWS Bedrock\n[External System — contract-tested only]\nNever called live in this repo — ADR-0003"]
    Foundry["Azure AI Foundry\n[External System — contract-tested only]\nNever called live in this repo — ADR-0003"]
    Otel["OpenTelemetry / Prometheus\n[External System]\nTraces and metrics"]

    Developer -->|"HTTPS, API key\nchat / agent run requests"| Aegis
    Operator -->|"HTTPS, admin API key\nvia the Console"| Aegis
    Aegis -->|"HTTP, only path actually\nexercised at runtime"| Ollama
    Aegis -.->|"never live here —\ncontract tests only"| Bedrock
    Aegis -.->|"never live here —\ncontract tests only"| Foundry
    Aegis -->|"OTLP / scrape"| Otel

    style Bedrock stroke-dasharray: 5 5
    style Foundry stroke-dasharray: 5 5
```

## Notes

- **Solid arrows** are calls that actually happen when you run this repository (`docker compose
  up`, CI). **Dashed arrows** to Bedrock/Foundry are calls that exist in fully-implemented code
  (`BedrockProvider`, `FoundryProvider`) but are only exercised against recorded fixtures in
  `tests/contract/` — see [ADR-0003](../adr/0003-local-first-contract-testing.md).
- The Operator's path through the Console (`console/`) still terminates at the same Aegis API —
  the console has no backend of its own, it's a pure client (see
  [container.md](container.md)).

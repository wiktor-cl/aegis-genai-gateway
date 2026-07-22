# CLAUDE.md — Aegis

> Ten plik jest aktualizowany po każdym ukończonym etapie (sprincie) projektu.
> Ostatnia aktualizacja: 2026-07-22 (po Sprint 3, Sprint 4 w toku).

## Czym jest Aegis i po co powstaje

Aegis to **enterprise multi-cloud GenAI agent gateway i runtime** — jedno API dla wielu
zespołów w organizacji, przez które przechodzi każde wywołanie modelu LLM. Centralizuje to,
co inaczej każdy zespół musiałby implementować osobno i niespójnie: wybór providera modelu,
politykę bezpieczeństwa (co wolno wysłać gdzie), kontrolę kosztów, multi-tenancy i audyt.

Projekt jest **portfolio project**, nie systemem produkcyjnym z realnym budżetem chmurowym.
Jego celem jest pokazanie kompetencji seniorskich w projektowaniu rozwiązań GenAI/enterprise:
warstwa abstrakcji providerów, routing oparty o politykę (nie o zaszyty na sztywno wybór
modelu), runtime agenta z pętlą tool-calling, guardrails (PII, prompt injection, wyciek
sekretów), kontrola kosztów z budżetami, multi-tenancy z RBAC egzekwowanym na poziomie
zapytania do bazy, evaluation gate wpięty w CI, observability (OpenTelemetry/Prometheus) oraz
recenzowalna (nigdy nie wdrażana) infrastruktura multi-cloud jako kod (Terraform/Bicep).

Każda nietrywialna decyzja architektoniczna ma swój ADR w `docs/adr/` — to one, nie ten plik,
są źródłem prawdy o "dlaczego tak", jeśli potrzebny jest pełny kontekst.

## Twarde ograniczenie: zero kosztów

**Ten projekt nigdy nie woła płatnego API i nigdy nie provisionuje zasobu w chmurze.** To
ograniczenie jest twarde i architektoniczne, nie tylko deklaratywne w README:

- Jedyny provider faktycznie wywoływany przez sieć — w testach, w docker-compose, w CI — to
  `LocalProvider`, rozmawiający z lokalną instancją Ollama. Zero kluczy API, zero ruchu
  wychodzącego do chmury, zero rachunku.
- `LocalProvider` jest **domyślnym** providerem w polityce routingu (`policies/routing.yaml`).
  `BedrockProvider` (AWS Bedrock) i `FoundryProvider` (Azure AI Foundry) to w pełni
  zaimplementowany, produkcyjnie wyglądający kod — ale w tym repo są ćwiczone wyłącznie przez
  **testy kontraktowe** wobec nagranych fixtures i fake'ów implementujących ten sam interfejs
  klienta (`tests/contract/`). Nigdy nie są wołane wobec prawdziwego konta AWS/Azure. Patrz
  [ADR-0003](docs/adr/0003-local-first-contract-testing.md).
- Infrastruktura jako kod (`infra/terraform` dla AWS, `infra/bicep` dla Azure — planowane w
  Sprincie 4) jest walidowana **wyłącznie statycznie**: `terraform validate` / `tflint` /
  `checkov` / `bicep build`. **`terraform apply` i `az deployment create` nigdy nie są
  uruchamiane** — CI nie ma i nie będzie miało żadnych poświadczeń chmurowych, którymi mogłoby
  to zrobić.
- Nic w tym repo nie jest twierdzeniem o wdrożeniu produkcyjnym. To twierdzenie o kodzie
  recenzowalnym, przetestowanym i gotowym-do-wdrożenia-w-takiej-formie — zweryfikowanym na tyle,
  na ile da się to zweryfikować za darmo.

## Stack

- **Język / runtime:** Python 3.12+
- **API:** FastAPI, Uvicorn (standard), Pydantic v2 + pydantic-settings
- **Baza danych:** PostgreSQL (asyncpg, SQLAlchemy 2.0 async, Alembic — migracje)
- **Cache / kolejka / rate limit:** Redis
- **HTTP client:** httpx
- **Providery LLM:** boto3 (AWS Bedrock), openai + azure-identity (Azure AI Foundry), lokalny
  klient Ollama (LocalProvider)
- **Tokenizacja:** tiktoken
- **Odporność:** tenacity (retry), własny per-provider circuit breaker
- **Bezpieczeństwo:** python-jose[cryptography] (JWT), argon2-cffi (hash kluczy API)
- **Observability:** structlog, OpenTelemetry (API/SDK + instrumentacja FastAPI + eksport
  OTLP), prometheus-client
- **Konfiguracja polityk:** YAML (routing, guardrails, pricing, tenants)
- **Testy:** pytest + pytest-asyncio, pytest-cov, respx (fake HTTP), moto (fake AWS),
  aiosqlite, testcontainers[postgres,redis] (integracyjne)
- **Jakość kodu:** ruff (lint), mypy (typowanie, `disallow_untyped_defs`)
- **Konsola operatora (Sprint 4):** React + TypeScript + Tailwind
- **IaC (Sprint 4, tylko walidacja statyczna):** Terraform (AWS), Bicep (Azure)
- **Konteneryzacja:** Docker, docker-compose (Postgres, Redis, Ollama, API — w pełni offline)
- **CI:** GitHub Actions (`.github/workflows/ci.yml`)

## Moduły (`src/aegis/`)

- **`providers/`** — warstwa abstrakcji `LLMProvider` (interfejs: `chat`, `embed`, `stream`,
  `call_tools`); implementacje `local_provider`, `bedrock_provider`, `foundry_provider`;
  `router.py` — routing oparty o politykę YAML z failoverem; `circuit_breaker.py` — osobny
  circuit breaker per provider.
- **`agent/`** — runtime agenta: pętla tool-calling z budżetami kroków/tokenów i retry
  (`runtime.py`), pełny trace przebiegu z deterministycznym replay (`trace.py`); `agent/tools/`
  — 4 narzędzia: knowledge base search, calculator, read-only SQL, allowlisted HTTP (z ochroną
  przed SSRF), plus `registry.py` i `base.py`.
- **`governance/`** — guardrails: redakcja PII (w tym walidacja numerów kart Luhn), screening
  prompt injection, blokowanie wycieku sekretów, walidacja outputu (`output_validation.py`),
  polityki per-tenant (`policies.py`), append-only audit log (`audit.py`), `pipeline.py` spinający
  wszystko w jeden przebieg.
- **`cost/`** — śledzenie kosztów per wywołanie (`tracker.py`), cennik providerów
  (`pricing.py`), budżety miesięczne z miękkim alertem i twardym stopem (`budgets.py`).
- **`tenancy/`** — multi-tenancy i RBAC: klucze API hashowane Argon2 z rotacją
  (`api_keys.py`), role (`admin`/`developer`/`viewer`) egzekwowane na poziomie zapytania do
  bazy, nie w warstwie prezentacji (`rbac.py`, patrz ADR-0005), modele (`models.py`).
- **`api/`** — punkty wejścia FastAPI: `routes_chat.py`, `routes_agent.py`, `routes_admin.py`,
  `routes_cost.py`.
- **`db/`** — modele SQLAlchemy (`models.py`), sesje async (`session.py`), baza deklaratywna
  (`base.py`), migracje Alembic (`migrations/`, w tym `0001_agent_runs_and_steps`,
  `0002_audit_cost_api_keys`).
- **`observability/`** — `tracing.py` (OpenTelemetry), `metrics.py` (Prometheus).
- **`eval/`** — harness ewaluacyjny wpinany w CI jako merge gate (Sprint 4, w trakcie —
  na razie tylko modele danych, `models.py`).
- **`config.py`, `main.py`** — konfiguracja aplikacji (pydantic-settings) i punkt startowy FastAPI.

Poza `src/aegis/`:
- **`policies/`** — `routing.yaml`, `guardrails.yaml`, `pricing.yaml`, `tenants.yaml`.
- **`console/`** — operatorska konsola React/TS/Tailwind (Sprint 4, jeszcze nie rozpoczęta —
  katalog istnieje pusty poza `src`).
- **`infra/`** — `terraform/` (AWS), `bicep/` (Azure) — planowane w Sprincie 4, tylko walidacja
  statyczna, nigdy `apply`/`deployment create`.
- **`tests/unit/`, `tests/integration/`, `tests/contract/`** — jednostkowe (bez zależności
  zewnętrznych), integracyjne (Testcontainers: Postgres, Redis), kontraktowe (nagrane fixtures,
  nigdy żywa sieć).
- **`docs/adr/`** — Architecture Decision Records; **`docs/architecture/`** — diagramy C4
  (Mermaid); `docs/threat-model.md`.

## Sprinty i status

- **[x] Sprint 1 — Provider abstraction layer.** `LLMProvider`, `LocalProvider` /
  `BedrockProvider` / `FoundryProvider`, routing polityk YAML z per-provider circuit breakingiem
  i failoverem, testy kontraktowe wobec nagranych fixtures, docker-compose.
  *(commit `b818a8c`)*
- **[x] Sprint 2 — Agent runtime.** Pętla tool-calling, budżety kroków/tokenów, retry, pełny
  trace przebiegu z deterministycznym replay, 4 narzędzia (knowledge base, calculator,
  read-only SQL, allowlisted HTTP z ochroną SSRF), przechowywanie trace w Postgresie z
  migracjami Alembic, OpenTelemetry + Prometheus na routerze providerów.
  *(commit `f9cee84`)*
- **[x] Sprint 3 — Governance, cost, multi-tenancy.** Guardrails (redakcja PII z walidacją
  Luhn, screening prompt injection, blokowanie wycieku sekretów, polityki per-tenant YAML),
  append-only audit log, śledzenie kosztów + egzekwowanie budżetu miesięcznego (miękki alert /
  twardy stop), multi-tenancy/RBAC (klucze API Argon2 z rotacją, role egzekwowane na poziomie
  zapytania do bazy — ADR-0005) wpięte w oba punkty wejścia API.
  *(commit `e75dba4`)*
- **[ ] Sprint 4 — Evaluation gate, konsola, IaC. W TRAKCIE.** Harness ewaluacyjny jako merge
  gate w CI, konsola operatora (React + TypeScript + Tailwind), IaC (Terraform dla AWS, Bicep
  dla Azure — tylko walidacja statyczna), pełna dokumentacja architektury (C4).

  Postęp:
  - [x] **Eval harness + eval-gate w CI.** `GoldenScriptProvider` (deterministyczny fake
    providera sterowany fixture'ami — [ADR-0008](docs/adr/0008-eval-gate-golden-fixtures.md)),
    runner wykonujący przypadki w trybie `chat` (przez `GuardrailPipeline`) i `agent` (przez
    prawdziwy `AgentRuntime` + prawdziwe narzędzia), scoring asercji, CLI
    (`python -m aegis.eval.cli`), 58 przypadków w `eval/cases/*.yaml` (chat_quality, tool_use,
    tool_safety, guardrails, robustness), job `eval-gate` w `.github/workflows/ci.yml`
    (wymaga 100% przejść), test regresyjny uruchamiający cały bank przypadków pod `pytest`.
    *(commit `c7d247a` + kolejny z przypadkami/CI)*
  - [ ] Konsola operatora (React + TypeScript + Tailwind) — nierozpoczęte.
  - [ ] IaC (Terraform AWS, Bicep Azure, tylko walidacja statyczna) — nierozpoczęte.
  - [ ] Diagramy C4 (`docs/architecture/`), `docs/cost-model.md`, `docs/runbook.md` —
    nierozpoczęte. `docs/threat-model.md` (STRIDE) już istnieje i jest kompletny sprzed tego
    etapu.

## Kluczowe decyzje architektoniczne

Pełna treść w `docs/adr/`. Skrót:

- **[ADR-0001](docs/adr/0001-provider-abstraction-layer.md) — warstwa abstrakcji providerów.**
  Jeden interfejs `LLMProvider` zamiast bezpośredniej integracji SDK w każdym zespole — chroni
  przed trwałym zrośnięciem kodu aplikacyjnego z jednym dostawcą.
- **[ADR-0002](docs/adr/0002-policy-based-routing.md) — routing oparty o politykę YAML.**
  Wybór providera to dane (`policies/routing.yaml`), nie kod — bo klasyfikacja danych i wymogi
  bezpieczeństwa różnią się per żądanie, nie per organizacja.
- **[ADR-0003](docs/adr/0003-local-first-contract-testing.md) — local-first, testy
  kontraktowe.** Trzy uzupełniające się mechanizmy zapewniające zero-cost development przy
  jednoczesnym realnym pokryciu testami integracji z Bedrock/Foundry — bez wywoływania żywych
  kont chmurowych. To jest fundament ograniczenia zero-kosztowego opisanego wyżej.
- **[ADR-0004](docs/adr/0004-postgres-for-audit-cost-and-trace.md) — jedna baza Postgres dla
  audytu, kosztów i trace.** Cztery różne obszary danych (`agent_runs`/`agent_steps`,
  `audit_log`, `cost_entries`, `api_keys`) żyją w jednej instancji Postgresa jako osobne tabele
  z jedną historią migracji Alembic, zamiast osobnej bazy per obszar.
- **[ADR-0005](docs/adr/0005-rbac-enforced-at-query-layer.md) — RBAC na poziomie zapytania do
  bazy.** Tenant pochodzi wyłącznie z uwierzytelnionego `Principal`, a filtrowanie uprawnień
  dzieje się przy zapytaniu do bazy, nie post-hoc w warstwie prezentacji — eliminuje klasę
  podatności "zapomniany filtr na końcu" prowadzącą do wycieku danych innego tenanta.
- **[ADR-0006](docs/adr/0006-per-provider-circuit-breaker.md) — circuit breaker per provider.**
  Każdy provider ma własny circuit breaker (CLOSED → OPEN po N kolejnych błędach → HALF_OPEN)
  zamiast jednej wspólnej pętli retry — zapobiega marnowaniu budżetu latencji i retry stormom
  wobec providera, który już wiadomo, że nie działa.
- **[ADR-0007](docs/adr/0007-multi-cloud-over-vendor-lock-in.md) — multi-cloud zamiast
  vendor lock-in.** AWS Bedrock i Azure AI Foundry jako równorzędni providerzy za tym samym
  interfejsem, bo organizacje wdrażające Aegis zwykle są już częściowo zaangażowane w jedną
  lub obie chmury z powodów niezwiązanych z GenAI (kontrakty, zgodność, rezydencja danych).

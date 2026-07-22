# ADR-0004: PostgreSQL for audit log, cost entries, and agent-run trace — one database, not one per concern

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

Sprint 2 wprowadził `agent_runs`/`agent_steps` (pełny trace przebiegu agenta). Sprint 3 dodaje
`audit_log` (kto/kiedy/jaki model/ile tokenów/jaka polityka), `cost_entries` (koszt per
wywołanie) i `api_keys` (klucze z rotacją). To cztery różne "obszary" danych, każdy z innym
wzorcem dostępu:

- `agent_runs`/`agent_steps` — zapis intensywny w trakcie runu, odczyt przy replay/debugowaniu.
- `audit_log` — wyłącznie insert, odczyt rzadki (compliance, incydent).
- `cost_entries` — insert per wywołanie, odczyt agregujący (SUM per tenant per miesiąc) na
  żądanie (raport, sprawdzenie budżetu).
- `api_keys` — mały wolumen, częste odczyty przy autentykacji każdego żądania.

Naturalne pytanie architektoniczne: czy to jedna baza, czy — jak często się robi w większych
systemach — osobna baza/instancja per obszar (np. dedykowany "audit store", osobny
"cost warehouse")?

## Decyzja

Wszystkie cztery obszary żyją w tej samej instancji PostgreSQL, jako osobne tabele z osobnymi
modelami SQLAlchemy (`src/aegis/db/models.py`), zarządzane jedną historią migracji Alembica.
Żaden serwis nie dostaje własnej bazy.

## Konsekwencje

### Pozytywne
- **Spójność transakcyjna tam, gdzie ma znaczenie.** Zapis kroku agenta, wpisu kosztowego i
  wpisu audytowego dla tego samego zdarzenia może odbyć się w jednej transakcji/sesji
  SQLAlchemy (patrz `AgentRuntime.run()` — `TraceStore`, `CostTracker`, `AuditStore` dzielą tę
  samą `AsyncSession`). Rozdzielenie na osobne bazy wymagałoby rozproszonej transakcji albo
  akceptacji niespójności ("koszt zapisany, audyt nie" po awarii w złym momencie).
- **Jeden operacyjny cel do backupu, monitoringu i uprawnień** na etapie, w którym wolumen
  (portfolio/PoC, nie tysiące żądań/s) w ogóle nie uzasadnia sharding'u czy osobnych instancji.
- **Raportowanie cross-obszarowe jest trywialne** — zapytanie "ile kosztował run X i co
  guardrails zrobiły po drodze" to jeden JOIN, nie zapytanie do dwóch systemów i ręczne
  sklejanie wyników.
- Prostszy runbook (`docs/runbook.md`): jedna baza do backupu/przywrócenia, nie N baz z N
  różnymi procedurami.

### Negatywne / koszty
- **Brak izolacji awarii.** Przeciążenie zapytaniami raportowymi po `cost_entries` teoretycznie
  może wpłynąć na zapis `agent_steps` w tej samej bazie. Mitygacja na przyszłość: osobne
  indeksy (już są — `ix_cost_entries_tenant_id`, `ix_cost_entries_created_at`) i, jeśli wolumen
  kiedyś to uzasadni, read replica pod raportowanie, bez zmiany modelu danych.
- **Różne wymagania retencji w jednej bazie.** `audit_log` być może musi być trzymany latami
  (compliance), a `agent_steps` można czyścić po 90 dniach (patrz `docs/runbook.md`) — to
  wymaga osobnej polityki retencji per tabela, nie per baza, co jest rozwiązywalne (partycjonowanie
  po dacie, osobne joby czyszczące), ale mniej "za darmo" niż przy fizycznie osobnych bazach.
- `audit_log` ma być insert-only; w jednej bazie z resztą aplikacji to reguła egzekwowana w
  kodzie (`AuditStore` nie ma metody update/delete) i docelowo uprawnieniami roli DB — nie ma
  fizycznej separacji, która by to wymusiła sama z siebie.

### Neutralne / do obserwacji
- Gdyby retencja/compliance dla audytu okazały się na tyle rygorystyczne, żeby wymagać osobnej,
  write-once infrastruktury (np. dedykowany magazyn append-only poza Postgresem), to naturalny
  kandydat do rewizji tej decyzji — ale to wymaga realnego wymogu, nie założenia z góry.

## Odrzucone alternatywy

### Osobna baza per obszar (agent trace / audit / cost)
Typowe w większych systemach enterprise, ale przedwczesne tutaj: dodaje operacyjną złożoność
(N baz do backupu, N connection stringów, potencjalnie rozproszone transakcje) bez korzyści
proporcjonalnej do obecnego wolumenu. Odrzucone na tym etapie; nic w modelu danych nie
uniemożliwia migracji pojedynczej tabeli do własnej bazy później, gdyby wolumen/compliance to
uzasadniły.

### Osobna baza specjalnie dla audytu (np. append-only log service, ClickHouse do kosztów)
Rozważane, bo to częsty wzorzec ("logi i metryki kosztowe do systemu analitycznego, nie do OLTP").
Odrzucone tutaj, bo (a) wolumen jest znikomy dla PoC, (b) wprowadza drugi system do
uruchomienia w ramach ograniczenia "zero kosztów, w pełni lokalnie" (kolejny kontener, kolejna
rzecz do nauczenia się przez recenzenta), (c) `docs/cost-model.md` pokazuje, że nawet przy 1000
użytkownikach wolumen wpisów nie zbliża się do skali, w której Postgres przestaje wystarczać.

### Redis zamiast Postgres dla cost_entries (szybkie liczniki)
Redis już jest w stacku (kolejka, rate limiting, cache — ADR z Sprint 1/2 infra). Rozważane dla
`cost_entries` jako szybkie liczniki per tenant. Odrzucone jako *jedyne* źródło prawdy: Redis
bez trwałości skonfigurowanej pod to zadanie ryzykuje utratę danych kosztowych przy restarcie, a
to są dane, które muszą przetrwać (raportowanie miesięczne, spory o fakturę). Może być
sensownym cache'em nad Postgresem później, nie zamiennikiem.

## Powiązane

- [[0001-provider-abstraction-layer]]
- `src/aegis/db/models.py`, `src/aegis/db/migrations/`
- `docs/runbook.md` — retencja i backup
- `docs/cost-model.md` — szacunek wolumenu przy 10/100/1000 użytkownikach

# ADR-0005: RBAC egzekwowane na poziomie zapytania do bazy, nie w warstwie prezentacji

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

Aegis ma trzy role (`admin`, `developer`, `viewer`) i wielu tenantów. Klasyczny, kruchy sposób
implementacji RBAC w API: pobrać dane, a potem "ukryć" w warstwie prezentacji/serializacji to,
czego wołający nie powinien widzieć (np. przefiltrować listę w handlerze przed zwróceniem JSON-a,
albo — gorzej — po stronie frontendu). Ten wzorzec ma znaną, powtarzalną klasę podatności: nowy
endpoint, refaktor istniejącego, albo debug print zapomniany w kodzie łatwo pomija filtr "na
końcu" i wycieka dane innego tenanta, bo dane w ogóle zostały pobrane z bazy przed sprawdzeniem
uprawnień.

Dla Aegis to nie jest teoretyczne ryzyko — `GET /v1/agents/runs/{run_id}` zwraca pełny trace
runu, który może zawierać fragmenty promptów, wyniki narzędzi (w tym odpowiedzi z bazy danych
przez `sql_query_readonly`), więc wyciek cross-tenant tutaj to bezpośredni wyciek danych innej
organizacji.

## Decyzja

Tenant, względem którego coś jest odpytywane, pochodzi wyłącznie z uwierzytelnionego
`Principal` (`aegis.tenancy.rbac.get_current_principal`, wyprowadzony z klucza API), nigdy z
treści żądania klienta. Metody warstwy danych przyjmują ten tenant jako parametr filtrujący
zapytanie SQL, a nie jako coś sprawdzane po fakcie:

```python
async def get_run(self, run_id: uuid.UUID, tenant_id: str | None = None) -> AgentRun | None:
    query = select(AgentRun).where(AgentRun.id == run_id)
    if tenant_id is not None:
        query = query.where(AgentRun.tenant_id == tenant_id)
    ...
```

`tenant_id=None` (dozwolone tylko dla roli `admin` w warstwie routingu) oznacza brak
ograniczenia; każda inna rola zawsze przekazuje swój `principal.tenant_id`. Skutek: wiersz
należący do innego tenanta nigdy nie trafia do pamięci procesu w pierwszej kolejności — `SELECT`
go po prostu nie zwraca, więc nie ma go czego "ukrywać" w serializacji.

Analogicznie: `POST /v1/agents/run` i `POST /v1/chat/completions` ignorują jakikolwiek
`tenant_id` w ciele żądania (celowo usunięty z modeli wejściowych) i zawsze używają
`principal.tenant_id`. `GET /v1/cost/report` honoruje parametr `tenant_id` z zapytania
wyłącznie dla roli `admin` — dla pozostałych ról niezgodność `tenant_id` z `principal.tenant_id`
to `403`, nie ciche przełączenie na własny tenant.

## Konsekwencje

### Pozytywne
- Klasa błędu "zapomniałem przefiltrować w handlerze" jest strukturalnie trudniejsza do
  popełnienia: filtr jest częścią sygnatury metody warstwy danych (`tenant_id` trzeba świadomie
  przekazać albo świadomie pominąć jako `None`), a nie osobnym krokiem po pobraniu danych.
- Testowalność: `tests/unit/test_api_agents.py` weryfikuje to zachowanie na realnym RBAC (klucz
  API, nie mock), włącznie z odmową dostępu, nie tylko "czy endpoint istnieje".
- Rola `admin` jako świadomy, jawny wyjątek (`tenant_id=None`) jest widoczna w code review —
  nie jest domyślnym zachowaniem, do którego trzeba by dojść przez brak filtra.

### Negatywne / koszty
- Każda nowa metoda odczytu w warstwie danych, która dotyczy danych tenant-scoped, musi
  świadomie powtórzyć ten wzorzec — nic w typie systemu nie wymusi tego automatycznie dla
  przyszłego, nienapisanego jeszcze zapytania. To ryzyko dyscypliny zespołu, udokumentowane
  tutaj wprost jako konwencja do przestrzegania.
- Więcej parametrów w sygnaturach metod (`tenant_id: str | None`) niż w wersji "pobierz
  wszystko, przefiltruj później" — celowy koszt czytelności w zamian za bezpieczeństwo.

### Neutralne / do obserwacji
- Gdyby liczba tenant-scoped zapytań znacząco urosła, naturalnym krokiem byłoby wprowadzenie
  Postgresowego Row-Level Security (RLS) jako drugiej warstwy obrony (baza sama odrzuca wiersze
  spoza `current_setting('app.tenant_id')`), tak żeby błąd w kodzie aplikacji nie był jedyną
  linią obrony. Nie wdrożone teraz — dodatkowa złożoność operacyjna nieuzasadniona przy obecnej
  liczbie tabel, ale zanotowana jako naturalny następny krok w `docs/threat-model.md`.

## Odrzucone alternatywy

### Filtrowanie w warstwie serializacji/prezentacji (API response)
Najczęstszy antywzorzec — pobierz wszystko, odetnij to, czego użytkownik nie powinien widzieć,
tuż przed zwróceniem JSON-a. Odrzucone: każdy nowy endpoint albo refaktor istniejącego
niesie ryzyko pominięcia tego kroku, a dane "niepowinny-widoczne" i tak trafiają do pamięci
procesu (i potencjalnie logów, cache'y, exception tracebacków) zanim zostaną odcięte.

### Filtrowanie wyłącznie w warstwie frontendu (konsola React)
Odrzucone kategorycznie — to nie jest kontrola bezpieczeństwa, to UX. Każdy klient API (nie
tylko konsola) może ominąć frontend całkowicie.

### Osobna baza/schema per tenant
Najsilniejsza izolacja, ale nieproporcjonalny koszt operacyjny (N schematów/baz do migracji,
backupu, monitoringu) dla obecnej skali i celu portfolio. Mogłoby mieć sens przy naprawdę
dużej liczbie dużych tenantów z twardym wymogiem izolacji fizycznej (np. regulacyjnym) — nie
tutaj.

## Powiązane

- [[0004-postgres-for-audit-cost-and-trace]]
- `src/aegis/tenancy/rbac.py`, `src/aegis/agent/trace.py`
- `docs/threat-model.md` — cross-tenant data leakage

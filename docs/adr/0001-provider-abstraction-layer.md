# ADR-0001: Warstwa abstrakcji providerów (`LLMProvider`) zamiast bezpośredniej integracji SDK w każdym zespole

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

Organizacja ma wiele zespołów, z których każdy chce korzystać z modeli LLM. Bez centralnej
warstwy każdy zespół integruje się bezpośrednio z SDK wybranego dostawcy (boto3 dla Bedrock,
azure-ai-* dla Azure OpenAI/Foundry, klient Ollama dla modeli lokalnych). To rodzi konkretne,
powtarzalne problemy:

- **Brak przenośności.** Kod aplikacyjny zespołu A jest trwale zrośnięty z Bedrock; migracja do
  innego dostawcy (zmiana cennika, wycofanie modelu, wymóg regulacyjny) oznacza przepisanie
  logiki biznesowej, nie tylko konfiguracji.
- **Niespójne wymuszanie polityk.** Klasyfikacja danych ("to jest poufne, nie może wyjść poza
  organizację"), limity kosztowe i guardrails muszą być egzekwowane w jednym miejscu. Jeśli
  każdy zespół woła SDK bezpośrednio, wymuszenie polityki wymaga N implementacji w N
  repozytoriach — w praktyce nie zostanie zrobione spójnie.
- **Brak wspólnej obserwowalności.** Bez wspólnej warstwy nie ma jednego miejsca, żeby zliczyć
  tokeny, koszt, trafienia guardraili i opóźnienie per model — każdy zespół musiałby to
  zbudować sam, albo (częściej) nikt tego nie zbuduje.
- **Twarde ograniczenie projektu portfolio:** Aegis nie może wywoływać żadnego płatnego API.
  Musi istnieć jeden interfejs, za którym w praktyce działa wyłącznie provider lokalny
  (Ollama), a implementacje chmurowe (Bedrock, Azure AI Foundry) są kompletne pod względem
  kodu, ale wołane wyłącznie w testach kontraktowych na nagranych fixture'ach. Bez wspólnego
  interfejsu nie da się tego w ogóle zbudować w sposób, który udaje przenośność.

## Decyzja

Definiujemy jeden interfejs `LLMProvider` (`src/aegis/providers/base.py`) z metodami:
`chat(...)`, `embed(...)`, `stream(...)`, `call_tools(...)` (tool-calling), operujący na
wspólnych, zdefiniowanych przez nas typach żądania/odpowiedzi (nie na typach natywnych SDK
danego dostawcy).

Implementacje:

- `LocalProvider` — jedyny provider faktycznie wywoływany w runtime; korzysta z lokalnego
  Ollama (lub sentence-transformers dla embeddingów). Jest domyślny.
- `BedrockProvider` — pełna implementacja na `boto3`, ale w CI/testach wołana wyłącznie przez
  fake spełniający ten sam kontrakt lub przez nagrane fixture'y JSON prawdziwych odpowiedzi
  Bedrock. Nigdy nie jest wywoływana z realnym kredentiałem AWS w tym repozytorium.
- `FoundryProvider` — analogicznie dla Azure AI Foundry / Azure OpenAI (`azure-ai-*`).

Wybór providera per żądanie nie jest zaszyty w kodzie wołającym — odpowiada za to osobny
router polityk (ADR-0002), który operuje wyłącznie na interfejsie `LLMProvider`, nigdy na
konkretnej implementacji.

## Konsekwencje

### Pozytywne
- Zamiana dostawcy (albo dodanie nowego, np. Google Vertex) to nowa implementacja jednego
  interfejsu, zero zmian w kodzie agentów ani w API wystawianym zespołom.
- Guardrails, liczenie kosztu, audyt i observability są wpięte raz, na granicy interfejsu —
  działają identycznie niezależnie od tego, który provider faktycznie odpowiedział.
- Możliwość budowy i pełnego przetestowania (kontraktowo) integracji z Bedrock i Azure AI
  Foundry bez wydania złotówki i bez zakładania kont w chmurze — kluczowe dla ograniczenia
  "zero kosztów" tego projektu.
- Testowalność: `LLMProvider` jako interfejs pozwala podstawić fake'a w testach jednostkowych
  runtime'u agenta bez uruchamiania żadnego providera.

### Negatywne / koszty
- Wspólny interfejs to najmniejszy wspólny mianownik możliwości dostawców — funkcje unikalne
  dla jednego SDK (np. specyficzny dla Bedrock guardrail natywny) wymagają albo pominięcia,
  albo rozszerzenia interfejsu o pola opcjonalne, co zwiększa jego złożoność w czasie.
  Traktujemy to świadomie — provider-specific ekstensje żyją w warstwie `extra`/`metadata`
  odpowiedzi, nie w rdzeniu interfejsu.
- Warstwa abstrakcji to dodatkowy kod do utrzymania i dodatkowy poziom pośredni przy debugowaniu
  (błąd trzeba czasem ścigać przez interfejs do konkretnej implementacji).
- Dopóki nie mamy realnych danych z produkcji, kontrakt interfejsu jest naszym najlepszym
  zgadywaniem co do wspólnego mianownika chat/embed/stream/tool-calling — może wymagać zmian po
  pierwszej integracji z realnym providerem chmurowym poza tym repozytorium.

### Neutralne / do obserwacji
- Liczba providerów w interfejsie (obecnie 3) jest mała; wartość abstrakcji rośnie z każdym
  kolejnym dostawcą — do zweryfikowania, czy w praktyce firma faktycznie dodaje więcej niż 2-3.

## Odrzucone alternatywy

### Bezpośrednia integracja SDK per zespół (status quo)
Najprostsze w krótkim terminie — zero kodu pośredniego, zespół używa boto3 czy azure-ai-*
tak, jak umie. Odrzucone, bo dokładnie to jest problemem, który Aegis ma rozwiązać: zerowa
przenośność, brak jednego miejsca na politykę i koszty, N-krotna duplikacja logiki
guardrails w N zespołach.

### Cienki reverse-proxy HTTP (bez wspólnego modelu domenowego)
Rozważaliśmy prosty proxy HTTP, który tylko przekierowuje żądanie do właściwego
dostawcy bez transformacji payloadu. Odrzucone — bez wspólnego modelu żądania/odpowiedzi
zespoły nadal piszą kod pod konkretny format odpowiedzi konkretnego dostawcy, więc
przenośność jest pozorna; guardrails i liczenie kosztu musiałyby parsować N różnych formatów.

### Framework orkiestracji agentów firm trzecich jako warstwa abstrakcji (np. gotowy framework multi-provider)
Dałoby szybszy start, ale: (a) uzależnia architekturę portfolio od czyjejś, niekontrolowanej
przez nas abstrakcji — słabo pokazuje kompetencję projektowania systemu; (b) typowe frameworki
tego typu zakładają realne wywołania sieciowe do skonfigurowania, co koliduje z wymogiem
"zero kosztów, w pełni lokalnie"; (c) trudniej pokazać w portfolio świadome decyzje
projektowe, skoro większość jest ukryta w zależności.

## Powiązane

- [[0002-policy-based-routing]]
- [[0003-local-first-contract-testing]]
- `docs/architecture/c4-component.md` — komponent Provider Layer

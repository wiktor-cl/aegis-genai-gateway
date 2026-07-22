# ADR-0003: Local-first, zero-cost development i testy kontraktowe dla providerów chmurowych

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

Aegis to projekt portfolio, nie system produkcyjny z budżetem i kontem chmurowym. Ma jednak
demonstrować realną integrację z AWS Bedrock i Azure AI Foundry, nie tylko podpięcie SDK bez
sprawdzenia, czy w ogóle działa. Twarde ograniczenie projektu (patrz README): **zero wywołań
płatnego API, zero zasobów w chmurze, nigdy `terraform apply`/`az deployment create`**.

To rodzi konkretne pytanie inżynierskie: jak przetestować `BedrockProvider`/`FoundryProvider`
(parsowanie odpowiedzi, mapowanie błędów, tool-calling) w sposób, który:
1. faktycznie coś sprawdza (nie jest testem atrapą, który zawsze przechodzi),
2. nigdy nie łączy się z prawdziwym AWS/Azure,
3. jest odporny na to, że recenzent/rekruter uruchomi `pytest` bez żadnych kluczy w środowisku.

## Decyzja

Trzy niezależne, uzupełniające się mechanizmy:

1. **`LocalProvider` jest jedynym providerem faktycznie wywoływanym przez sieć** w testach
   integracyjnych, docker-compose i CI — mówi z lokalnym Ollama, zero kosztu, zero danych
   wychodzących poza maszynę.
2. **`BedrockProvider`/`FoundryProvider` przyjmują wstrzykiwany klient** (`client: Any | None`
   w konstruktorze). W produkcji `None` oznacza "zbuduj prawdziwego boto3/AzureOpenAI clienta
   leniwie, przy pierwszym wywołaniu". W testach zawsze wstrzykiwany jest fake
   (`tests/contract/fakes.py`) implementujący dokładnie tę samą powierzchnię wywołań
   (`converse`, `converse_stream`, `invoke_model` / `chat.completions.create`,
   `embeddings.create`), zwracający dane z **nagranych fixture'ów JSON**
   (`tests/contract/fixtures/{bedrock,foundry}/*.json`) odzwierciedlających realny kształt
   odpowiedzi tych API (w tym błędów: throttling, brak autoryzacji).
3. **Fixture'y dla Foundry są walidowane przez prawdziwe modele Pydantic z pakietu `openai`**
   (`ChatCompletion.model_validate(...)`, `CreateEmbeddingResponse.model_validate(...)`) —
   jeśli SDK zmieni kształt odpowiedzi w nowej wersji, test kontraktowy się wysypie, zanim
   wysypie się kod produkcyjny.

Efekt: `BedrockProvider`/`FoundryProvider` są kompletnym, deployowalnym kodem — realny zespół
z prawdziwym kontem AWS/Azure mógłby go użyć bez zmian — ale w tym repozytorium nigdy nie
dotykają sieci poza `localhost`.

## Konsekwencje

### Pozytywne
- `pytest` przechodzi w pełni offline, bez jakichkolwiek kluczy w środowisku — kluczowe dla
  recenzenta/rekrutera klonującego repo.
- Testy kontraktowe realnie wychwytują regresje w mapowaniu odpowiedzi/błędów (np. zmiana
  nazwy pola w kodzie parsującym natychmiast psuje test), w odróżnieniu od testów, które tylko
  sprawdzają "czy funkcja się nie wywaliła".
- Jasna, udokumentowana granica: nikt przeglądający kod nie musi się zastanawiać, czy
  uruchomienie testów przypadkiem obciąży czyjeś konto AWS.

### Negatywne / koszty
- Fixture'y są utrzymywane ręcznie i mogą z czasem rozjechać się z prawdziwym kształtem
  odpowiedzi Bedrock/Azure (te API też ewoluują). Mitygacja częściowa: fixture'y Foundry są
  walidowane przez rzeczywiste typy SDK `openai`, więc przynajmniej ta strona kontraktu jest
  pilnowana automatycznie; fixture'y Bedrock (surowe dict, bo boto3 nie ma statycznych typów
  odpowiedzi z `converse`) nie mają takiej gwarancji i wymagają ręcznej czujności.
- To *nie jest* dowód, że integracja zadziała na prawdziwym koncie AWS/Azure (np. realne IAM,
  limity, network path w VPC) — tylko dowód, że logika parsowania/mapowania błędów jest
  poprawna względem udokumentowanego kształtu API. README i ten ADR mówią o tym wprost, żeby
  nie sugerować gotowości produkcyjnej, której nie zweryfikowaliśmy.

### Neutralne / do obserwacji
- Gdyby ten projekt kiedyś dostał prawdziwe konto testowe AWS/Azure (poza zakresem tego
  repozytorium), naturalnym kolejnym krokiem byłoby dodanie osobnej, jawnie oznaczonej
  warstwy testów E2E uruchamianych ręcznie/poza CI — nie zastępując tym testów kontraktowych,
  które i tak powinny zostać jako szybka, darmowa siatka bezpieczeństwa.

## Odrzucone alternatywy

### `moto` (symulacja AWS) jako jedyna metoda testowania Bedrock
`moto` jest w zależnościach deweloperskich i nadaje się do testowania integracji z usługami
AWS o dojrzałym wsparciu w moto (np. IAM w kontekście przyszłych testów IaC). W czasie pisania
tego ADR wsparcie `moto` dla Bedrock Runtime (`converse`/`converse_stream`) jest niepełne
względem najnowszego API — poleganie wyłącznie na nim ryzykowałoby fałszywe poczucie pokrycia.
Fake + nagrane fixture'y dają pełną kontrolę nad kształtem odpowiedzi, włącznie z przypadkami
błędów, których `moto` może jeszcze nie modelować.

### Rzeczywiste wywołania na darmowym/trial koncie AWS/Azure
Odrzucone kategorycznie przez twarde ograniczenie projektu — nawet warstwa darmowa/trial
wymaga karty płatniczej i podlega limitom, których nie da się zagwarantować z poziomu CI
uruchamianego przez nieznane osoby (recenzentów). Niezgodne z wymogiem "zero zasobów w
chmurze, nigdy nie wywołuj płatnego API".

### Testowanie tylko "happy path" bez nagranych błędów (throttling, auth)
Szybsze do napisania, ale pomija dokładnie te ścieżki, które w praktyce najbardziej interesują
architekturę enterprise: czy błąd 429 z Bedrock faktycznie uruchamia failover routera (ADR-0002),
czy błąd 403 faktycznie *nie* uruchamia failoveru (bo to błąd konfiguracji, nie przejściowa
awaria). Odrzucone — brak testu na te ścieżki byłby luką w dokładnie tym, co ten projekt ma
demonstrować.

## Powiązane

- [[0001-provider-abstraction-layer]]
- [[0002-policy-based-routing]]
- `tests/contract/` — testy i fixture'y
- README — sekcja "Co jest realnie uruchamiane, a co tylko zaimplementowane"

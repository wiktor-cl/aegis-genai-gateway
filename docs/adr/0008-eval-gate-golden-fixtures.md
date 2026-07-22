# ADR-0008: Golden-fixture provider dla eval-gate zamiast żywego modelu w CI

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

Sprint 4 wprowadza harness ewaluacyjny (`src/aegis/eval/`) wpięty w CI jako merge gate: pull
request zmieniający prompt, politykę routingu albo regułę guardrails musi przejść zestaw
przypadków ewaluacyjnych, zanim zostanie zmergowany (patrz `knowledge_base_docs.json`, kb-006).

To rodzi to samo pytanie inżynierskie co ADR-0003, tylko na poziomie warstwy agenta zamiast
providera: jak przetestować pętlę tool-calling, guardrails i scoring w sposób, który

1. faktycznie coś sprawdza (regresja w prawdziwym kodzie musi zepsuć test),
2. nigdy nie wywołuje żywego, płatnego ani nawet lokalnego-ale-niedeterministycznego modelu w CI
   (twarde ograniczenie zero-cost z README dotyczy też CI, nie tylko produkcji),
3. jest deterministyczny — ten sam commit musi dawać ten sam wynik eval-gate za każdym razem,
   inaczej "merge gate" staje się loterią, a nie kontrolą jakości.

Naiwna opcja — uruchomić `LocalProvider` przeciwko prawdziwej Ollamie w CI — łamie (2) i (3)
jednocześnie: runner GitHub Actions nie ma GPU ani czasu na sensowny model w rozsądnym budżecie
czasowym joba, a nawet gdyby miał, odpowiedzi lokalnego LLM nie są bit-identyczne między
uruchomieniami (temperatura, kolejność tokenizacji, wersja modelu) — więc "regresja" i "zwykła
wariancja modelu" byłyby nierozróżnialne.

## Decyzja

Eval-gate w CI nigdy nie wywołuje żadnego prawdziwego modelu. Zamiast tego każdy `EvalCase`
(`src/aegis/eval/models.py`) niesie **złote fixtures**: `golden_tool_calls` i
`golden_final_text` opisują, co zrobiłby "znany dobry" model dla tego przypadku. `GoldenScriptProvider`
(`src/aegis/eval/golden_provider.py`) implementuje `LLMProvider` i po prostu odtwarza ten
scenariusz — dokładnie ten sam wzorzec co `ScriptedProvider` w `tests/unit/test_runtime.py`,
tylko sterowany danymi z pliku YAML zamiast zakodowany w teście.

To, co eval-gate faktycznie weryfikuje, to **nie** "czy model odpowiada dobrze" (to wymagałoby
żywego, niedeterministycznego modelu — poza zakresem tego repo), tylko:

- czy pętla tool-calling (`AgentRuntime`) poprawnie wykonuje narzędzia, których "model" zażądał,
  z właściwymi argumentami, w prawdziwym `ToolRegistry` z prawdziwymi narzędziami,
- czy guardrails (PII, prompt injection, secret leak) faktycznie blokują/redagują na
  wejściu/wyjściu, wpięte w tę samą pętlę co produkcyjnie,
- czy zmiana w `policies/*.yaml`, w kodzie guardrails, w routingu czy w scoringu asercji
  faktycznie psuje test, zamiast przechodzić milcząco.

Wszystko poza samym providerem jest prawdziwym kodem produkcyjnym: prawdziwy `AgentRuntime`,
prawdziwe narzędzia (`calculator`, `knowledge_base_search`, `sql_query_readonly` na SQLite
w pamięci, `http_get` z realną walidacją SSRF — sieciowe wywołanie samo w sobie jest mockowane
przez `respx` tylko dla przypadków, które celowo testują udany fetch, nigdy dla ścieżek
odrzucenia, które nie dotykają sieci w ogóle), prawdziwy `GuardrailPipeline` z prawdziwych
plików `policies/guardrails.yaml`.

Zespół z prawdziwym kontem/modelem może uruchomić dokładnie ten sam zestaw przypadków w trybie
`chat` przeciwko żywemu `LocalProvider`/Ollamie lokalnie (`eval/README.md` opisuje jak) — to
narzędzie deweloperskie, nie część CI. Eval-gate w CI i "oceń jakość żywego modelu" to dwa
osobne, uzupełniające się use case'y, tak jak w ADR-0003 kontrakt testowy i żywe konto AWS/Azure
to dwa osobne use case'y.

## Konsekwencje

### Pozytywne
- CI pozostaje w pełni offline, deterministyczne i darmowe — spójne z ADR-0003 i README.
- Regresja w prawdziwym kodzie (np. `AgentRuntime` przestaje przekazywać argumenty narzędzia,
  `GuardrailPipeline` przestaje blokować prompt injection) psuje eval-gate, ponieważ te
  komponenty są prawdziwe — jedyną atrapą jest "model".
- Fixture'y golden są czytelne dla recenzenta jako dokumentacja oczekiwanego zachowania: plik
  YAML wprost mówi "dla tego promptu narzędzie X powinno zostać wywołane z argumentem Y".

### Negatywne / koszty
- Eval-gate **nie** wykrywa regresji jakości samego modelu (np. gorszy model zaczyna źle
  formatować odpowiedzi) — to jest świadomie poza zakresem, bo wymagałoby żywego, płatnego lub
  niedeterministycznego wywołania. Zespół z realnym budżetem powinien dołożyć osobny,
  ręcznie/nightly uruchamiany eval przeciwko żywemu modelowi — nieopisany w tym ADR, bo poza
  zakresem zero-cost tego repo.
- Fixture'y golden wymagają ręcznej aktualizacji, gdy zmienia się oczekiwane zachowanie (np.
  nowa reguła routingu zmienia który provider powinien odpowiadać) — analogiczny koszt
  utrzymania do fixture'ów kontraktowych z ADR-0003.

### Neutralne / do obserwacji
- Próg przejścia eval-gate jest ustawiony na 100% (`min_pass_rate=1.0` w CLI) — bo fixture'y są
  w pełni deterministyczne i ręcznie zweryfikowane; każdy fail oznacza albo regresję, albo
  fixture wymagający aktualizacji, nigdy "zwykłą wariancję". Gdyby w przyszłości dodano tryb
  przeciwko żywemu modelowi, ten próg musiałby się obniżyć dla tamtego trybu — nie dla tego.

## Odrzucone alternatywy

### Uruchomienie realnej, małej Ollamy w CI z ustawioną `temperature=0`
Rozważone i odrzucone: nawet przy `temperature=0` różne wersje/buildy silnika inferencji nie
gwarantują bit-identycznych wyników między uruchomieniami runnera GitHub Actions, a ściągnięcie
i uruchomienie modelu (nawet małego) w każdym jobie CI kosztuje kilka minut i kilka GB — zbyt
drogie i zbyt kruche jako bramka blokująca merge.

### Mockowanie na poziomie `AgentRuntime` zamiast na poziomie providera
Odrzucone: mockowanie wyżej (np. podstawienie fałszywego `AgentRuntime.run()`) sprawiłoby, że
eval-gate nie testowałby w ogóle prawdziwej pętli tool-calling ani guardrails — dokładnie tych
komponentów, które ten sprint ma zweryfikować. Mockowanie na najniższym możliwym poziomie
(sam provider, tak jak w ADR-0003) maksymalizuje ilość prawdziwego kodu na ścieżce testu.

## Powiązane

- [[0001-provider-abstraction-layer]]
- [[0002-policy-based-routing]]
- [[0003-local-first-contract-testing]]
- `src/aegis/eval/` — implementacja
- `eval/cases/` — przypadki (fixture'y golden)
- `.github/workflows/ci.yml` — job `eval-gate`

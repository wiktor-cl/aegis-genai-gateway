# ADR-0002: Routing polityk (YAML) zamiast jednego, na stałe wybranego modelu

- **Status:** Accepted
- **Data:** 2026-07-22
- **Autor:** wiktor-cl

## Kontekst

ADR-0001 daje nam jeden interfejs `LLMProvider`, ale nie mówi, *który* provider obsłuży
dane żądanie. Naiwne rozwiązanie — jeden globalnie skonfigurowany model/provider dla całej
organizacji — nie odzwierciedla rzeczywistości firmy z kontekstu produktowego Aegis:

- **Klasyfikacja danych różni się per żądanie, nie per organizacja.** To samo API może
  obsługiwać zapytanie o dane publiczne (FAQ produktowe) i zapytanie zawierające dane
  poufne (dane klienta, kod źródłowy, PII). Tylko pierwsze wolno wysłać do modelu w chmurze
  publicznej; drugie musi zostać lokalnie. Jeden globalny provider nie potrafi tego rozróżnić.
- **Koszt i jakość to kompromis, który zespoły chcą kręcić, nie programiści Aegis.** Zespół
  obsługi klienta może chcieć taniego, szybkiego modelu; zespół prawny może wymagać
  najwyższej jakości niezależnie od kosztu. To decyzja polityczna/biznesowa, nie
  architektoniczna — nie powinna wymagać zmiany i redeployu kodu gateway'a.
- **Awaria dostawcy nie może być awarią całego systemu.** Bedrock ma przestój albo
  rate-limituje → żądania kwalifikujące się do chmury muszą mieć zdefiniowaną ścieżkę
  odwrotu (do innego dostawcy albo do providera lokalnego), inaczej cały ruch stoi.
- Wymuszenie tego jako logiki w kodzie (np. `if tenant == "legal": use_bedrock()`) rozprasza
  regułę biznesową po całej bazie kodu i wymaga PR-a + redeployu przy każdej zmianie polityki.

## Decyzja

Decyzja o wyborze providera jest danymi, nie kodem: `policies/routing.yaml`, wczytywanym
i walidowanym przez `RoutingPolicy` (`src/aegis/providers/router.py`). Struktura:

- `providers` — dostępni kandydaci i ich metadane (model, region, cennik).
- `rules` — lista reguł ocenianych od góry, pierwsze dopasowanie wygrywa; każda reguła ma
  warunek (`when`: klasyfikacja danych, poziom kosztu) i uporządkowaną listę kandydatów
  (`allow`).
- `failover` — liczba prób i parametry per-providerowego circuit breakera.

`ProviderRouter.route()` bierze `RoutingContext` (tenant, klasyfikacja danych, poziom kosztu),
wyznacza uporządkowaną listę kandydatów z polityki i próbuje ich po kolei, z circuit breakerem
pomijającym dostawców w stanie OPEN. Reguła, która nigdy nie może zostać osłabiona:
`confidential`/`restricted` rozwiązuje się wyłącznie do `local` — patrz
`docs/threat-model.md`, sekcja o wycieku danych przez błędny routing.

## Konsekwencje

### Pozytywne
- Zmiana polityki (np. "zespół X dostaje wyższy budżet kosztowy") to edycja YAML i redeploy
  konfiguracji, nie zmiana kodu aplikacji.
- Reguła "dane poufne nigdy nie opuszczają organizacji" jest wyrażona jawnie, w jednym pliku,
  łatwym do code-review przez zespół bezpieczeństwa — nie jest rozproszona po handlerach.
- Failover i circuit breaking są własnością routera, nie każdego providera z osobna — provider
  implementuje tylko "jak rozmawiać z backendem", nie "co zrobić, gdy backend nie odpowiada".

### Negatywne / koszty
- Poprawność systemu zależy teraz od poprawności pliku konfiguracyjnego, nie tylko kodu — błąd
  w YAML (literówka w nazwie klasyfikacji) może po cichu przepuścić żądanie tam, gdzie nie
  powinno trafić. Mitygacja: `RoutingPolicy` to model Pydantic, który odrzuca nieznane/źle
  otypowane pola przy starcie aplikacji, nie w trakcie obsługi żądania.
- Reguły ewaluowane "pierwsze dopasowanie wygrywa" wymagają dyscypliny przy dodawaniu nowych
  reguł (kolejność ma znaczenie) — udokumentowane wprost w komentarzu w `routing.yaml`.

### Neutralne / do obserwacji
- Obecny model reguł (płaskie `when`/`allow`) jest celowo prosty. Gdyby w przyszłości
  potrzebne było routowanie po dodatkowych wymiarach (np. region rezydencji danych, SLA
  latencji), będzie to rozszerzenie `RoutingRule`, nie przeprojektowanie routera.

## Odrzucone alternatywy

### Jeden globalny model/provider dla całej organizacji
Najprostsze, ale nie spełnia wymogu "dane poufne nigdy nie trafiają do chmury publicznej" bez
segregacji ruchu na poziomie żądania — musiałoby albo zawsze być lokalne (marnując jakość/koszt
tam, gdzie chmura byłaby bezpieczna i tańsza), albo zawsze chmurowe (łamiąc wymóg poufności).

### Reguły zaszyte w kodzie (if/else per tenant/klasyfikacja)
Szybkie do napisania, ale każda zmiana polityki wymaga PR-a, code review i redeployu gateway'a.
W organizacji z wieloma zespołami i częstymi zmianami polityk kosztowych to wąskie gardło
operacyjne — dokładnie to Aegis ma rozwiązać (patrz kontekst produktowy w README).

### Silnik reguł ogólnego przeznaczenia (np. OPA/Rego, CEL)
Rozważane dla większej ekspresywności. Odrzucone na tym etapie: dodaje zależność i język do
nauczenia się dla marginalnej korzyści przy obecnej złożoności reguł (klasyfikacja × koszt).
Jeśli reguły routingu urosną do potrzeby pełnej logiki warunkowej/zagnieżdżonej, to kandydat
do rewizji tej decyzji, nie coś do wdrożenia przedwcześnie.

## Powiązane

- [[0001-provider-abstraction-layer]]
- [[0003-local-first-contract-testing]]
- `docs/threat-model.md` — wyciek danych przez błędny routing
- `policies/routing.yaml`

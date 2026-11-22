# Ceny dynamiczne energii

Taryfa dynamiczna jest wyceniana na podstawie rzeczywistych cen rynkowych pobieranych
automatycznie z PSE. Ceny trafiają do bazy przez worker synchronizacji; kalkulator symulacji
czyta je wyłącznie z bazy i nie odpytuje dostawcy.

## Źródło danych: PSE – Rynkowa Cena Energii (RCE)

| | |
|---|---|
| Dostawca | Polskie Sieci Elektroenergetyczne, publiczne API raportowe (bez klucza) |
| Endpoint | `GET https://api.raporty.pse.pl/api/rce-pln?$filter=business_date eq 'RRRR-MM-DD'` |
| Protokół | OData: odpowiedź `{"value": [...], "nextLink": "..."}`, maks. 100 rekordów na stronę |
| Rozdzielczość | 15 minut: 96 rekordów na dobę (92 lub 100 w dniach zmiany czasu) |
| Jednostka | PLN/MWh, cena **może być ujemna** |
| Publikacja | ok. 13:45 w dniu D-1 dla doby D (pole `publication_ts`) |
| Dostępność | od 2024-06-14 (dla wcześniejszych dat API zwraca pustą listę) |

Przykładowy rekord:

```json
{
  "business_date": "2025-01-01",
  "period": "00:00 - 00:15",
  "period_utc": "23:00 - 23:15",
  "dtime": "2025-01-01 00:15:00",
  "dtime_utc": "2024-12-31 23:15:00",
  "rce_pln": 16.26,
  "publication_ts": "2024-12-31 13:44:06.711"
}
```

Mapowanie w adapterze `PseRcePriceProvider`:

- `interval_start = dtime_utc - długość(period_utc)`, zapisywane jako `timestamptz` w UTC.
  `dtime_utc` oznacza **koniec** interwału.
- Pola lokalne (`dtime`, `period`) są ignorowane. W dniu zmiany czasu PSE zwraca w nich
  wartości typu `02a:15`, których nie da się jednoznacznie sparsować.
- `business_date` to doba handlowa w strefie Europe/Warsaw.
- `rce_pln` jest zapisywane bez zmian, w PLN/MWh.

## Źródło danych: PSE – miesięczna cena RCEm

RCEm to średnia ważona RCE z miesiąca, bez VAT i akcyzy, w zł/MWh. PSE nie udostępnia jej przez API,
tylko jako tabelę na stronie
[RCEm](https://www.pse.pl/oire/rcem-rynkowa-miesieczna-cena-energii-elektrycznej). Publikacja jest
ok. 11. dnia następnego miesiąca, a korekty pojawiają się w wierszu „skorygowana RCEm”.
`PseRcemProvider` (`app/providers/prices/pse_rcem_provider.py`) czyta całą tabelę, a korekta
nadpisuje pierwszą publikację.

### Wycena energii oddanej w net-billingu

Według nowelizacji ustawy o OZE z 27.11.2024 (Dz.U. 2024 poz. 1847)
`PVBalancingEngine.get_price_for_pv_energy` wycenia energię oddaną tak:

| okres | cena | współczynnik depozytu |
|---|---|---|
| do 31.01.2025 | RCE z kwadransa (dla wszystkich) | 1,00 |
| od 1.02.2025 | RCEm albo RCE, według `pv_config.type_of_price` w profilu | 1,23 |

Ujemna cena daje 0. Ta sama wycena jest stosowana w Optymalizacji dla kwadransów z nadwyżką PV.
Zwrotu niewykorzystanej nadpłaty (20% przy RCEm, 30% przy RCE) nie modelujemy.

## Architektura

```
app/providers/prices/
  base.py               PriceProvider (kontrakt), PricePoint (DTO), wyjątki
  pse_provider.py       adapter PSE: HTTP, stronicowanie nextLink, mapowanie na UTC
  retrying_provider.py  dekorator: retry z backoffem 2s/4s/8s dla błędów przejściowych
app/repositories/
  dynamic_price_repository.py    upsert (ON CONFLICT), odczyty
  price_sync_run_repository.py   historia i status synchronizacji
app/services/
  price_sync_service.py   orkiestracja: które doby, pobranie, zapis, status
  pricing_strategies.py   wycena taryf: FixedRatePricing / DynamicMarketPricing
app/core/
  price_sync_factory.py   jedyne miejsce wyboru konkretnego dostawcy
  locks.py                pg_advisory_lock: API i worker nie synchronizują jednocześnie
app/workers/price_sync_worker.py  APScheduler + komendy CLI
```

**Zmiana źródła** (np. ENTSO-E albo API konkretnego sprzedawcy):

1. Dodaj klasę z atrybutem `source` i metodą `fetch_day(date) -> list[PricePoint]`.
2. Podmień ją w `build_price_provider()` w `app/core/price_sync_factory.py`.

Serwis, repozytoria, worker i endpointy pozostają bez zmian.

## Tabele

**`rce_price_observations`**: jedna obserwacja ceny.

| kolumna | opis |
|---|---|
| `source` | identyfikator źródła, np. `pse_rce` |
| `interval_start` | początek interwału, `timestamptz` (UTC) |
| `interval_minutes` | długość interwału (15) |
| `business_date` | doba handlowa (Europe/Warsaw) |
| `price_pln_mwh` | cena w PLN/MWh, `numeric(12,4)` |
| `created_at`, `updated_at` | czas pierwszego zapisu i ostatniej aktualizacji |

Ograniczenie `UNIQUE(source, interval_start)` w połączeniu z `INSERT ... ON CONFLICT DO UPDATE`
zapewnia idempotencję. Ponowny import tego samego okresu aktualizuje ceny i nie tworzy duplikatów.

**`rcem_price_observations`**: cena RCEm miesiąca. Kolumny: `source` (`pse_rcem`), `price_month`
(pierwszy dzień miesiąca), `price_pln_mwh`, `published_at`. Unikalność `(source, price_month)`.

**`price_sync_runs`**: historia uruchomień. Zawiera trigger (`scheduled`/`manual`/`cli`),
zakres dat, status, liczbę dób i rekordów oraz `error_message`.

| status | znaczenie |
|---|---|
| `running` | w trakcie |
| `success` | pobrano wszystkie żądane doby |
| `partial` | część dób pobrana, dla części brak danych lub błąd |
| `no_data` | dostawca nie opublikował jeszcze danych (np. jutro przed 13:45) |
| `failed` | błąd dostawcy i nic nie zapisano, albo nieoczekiwany błąd |

## Worker

Worker działa jako osobny kontener `price-worker` w `docker-compose.yml`.

- Codziennie o 15:00 Europe/Warsaw (`PRICE_PUBLICATION_TIME`; PSE publikuje ceny na jutro ok. 13:45)
  uzupełnia brakujące lub niepełne doby z ostatnich `CATCHUP_DAYS` (7) dni oraz jutro.
- Przy starcie robi to samo, więc nadrabia przestój.
- Jeśli PSE jeszcze nie opublikowało jutra, kolejne uruchomienie dociągnie tę dobę w ramach okna catch-up.
- Przy starcie i codziennie o 15:30 pobiera całą tabelę RCEm. Błąd tej synchronizacji jest logowany
  i nie zatrzymuje harmonogramu.

```bash
python -m app.workers.price_sync_worker run                            # harmonogram
python -m app.workers.price_sync_worker once                           # jednorazowo uzupełnij braki
python -m app.workers.price_sync_worker backfill 2024-06-14 2025-12-31 # historia (paczki po 31 dni)
python -m app.workers.price_sync_worker rcem                          # ceny RCEm ze strony PSE
```

Bez Dockera ten sam efekt da cron: `0 15 * * * cd backend && python -m app.workers.price_sync_worker once`.

## Endpointy

| metoda | ścieżka | autoryzacja | opis |
|---|---|---|---|
| POST | `/api/v1/dynamic-prices/sync` | nagłówek `X-Admin-Key` | ręczna synchronizacja |
| GET | `/api/v1/dynamic-prices/sync/status` | JWT | ostatnie uruchomienie i ostatnie udane |
| GET | `/api/v1/dynamic-prices?business_date=RRRR-MM-DD` | JWT | ceny z doby (PLN/MWh i PLN/kWh) |
| GET | `/api/v1/dynamic-prices/history?from=&to=&resolution=` | JWT | historia cen do wykresu, średnia, kompletność dni |
| GET | `/api/v1/dynamic-prices/tomorrow/insights?window=2h` | JWT | najtańsze i najdroższe okno cenowe jutra |

### Okna cenowe na jutro

`GET /tomorrow/insights` zwraca dane do prostych komunikatów („najtaniej jutro 12:00–14:00”).

- `window`: długość okna, wielokrotność 15 minut od `15min` do `12h` (np. `2h`, `90min`); domyślnie `2h`.
  Okno przesuwa się co kwadrans.
- Ceny to zawsze ceny oferty dynamicznej operatora z profilu, liczone przez `SchedulePriceService`: RCE z marżą
  i limitami oferty, opłaty za kWh, VAT. Dla klienta z ceną dynamiczną są takie same jak w
  `GET /energy-files/{id}/schedule`. Klient ze zwykłą taryfą ma `profile_dynamic: false`; dystrybucja jest wtedy
  z jego grupy, a gdy oferta dynamiczna jej nie obejmuje, z pierwszej grupy oferty (pole `tariff` ją opisuje).
- `cheapest` i `most_expensive`: `start`, `end` (Europe/Warsaw), `average_price_pln_kwh`, `difference_percent`
  względem średniej dobowej (`average_price_pln_kwh` odpowiedzi). Przy remisie wygrywa wcześniejsze okno.
  Procent liczony jest względem modułu średniej, więc przy ujemnej średniej „taniej” nadal jest na minusie;
  przy średniej równej 0 ma wartość `null`.
- Okna liczone są na kwadransach w UTC, więc doba 92 i 100 kwadransów działa bez wyjątków
  (`intervals`, `expected_intervals`).
- `flat_prices: true`, gdy najdroższy i najtańszy kwadrans doby różnią się o mniej niż
  `FLAT_PRICE_SPREAD_PLN_KWH` (domyślnie 0,05 zł/kWh). Okna są nadal zwracane.
- Brak kompletu cen dynamicznych na jutro: `status: "unavailable"`, bez okien, z `expected_publication_at`
  (dzisiaj o `PRICE_PUBLICATION_TIME`, domyślnie 15:00 — o tej godzinie worker pobiera ceny opublikowane
  przez PSE ok. 13:45). Godzina w przeszłości oznacza opóźnienie publikacji albo synchronizacji.
- Brak stawek w cenniku na jutro (operator nie ma oferty dynamicznej, jej cennik nie obejmuje jutra albo brakuje
  okresu opłat regulacyjnych): `status: "no_tariff_data"`, bez okien i bez `expected_publication_at`, bo publikacja
  RCE tego nie zmieni. Gdy brakuje i stawek, i cen RCE, wygrywa `no_tariff_data`.
- Kody: `401` bez tokenu, `409` bez uzupełnionego profilu, `422` przy złym `window`.

Szczegóły `POST /sync`:

- Bez body działa jak zadanie workera.
- Z body `{"date_from": "...", "date_to": "..."}` pobiera ponownie wskazane doby (maks. 31 dni).
- Kody odpowiedzi:
  - `200`: zwraca rekord uruchomienia ze statusem;
  - `401`: zły klucz;
  - `409`: synchronizacja już trwa;
  - `422`: zły zakres;
  - `503`: brak skonfigurowanego `PRICE_SYNC_ADMIN_KEY`.

## Obsługa błędów

| sytuacja | zachowanie |
|---|---|
| timeout, błąd połączenia, HTTP 5xx/429 | 3 próby z backoffem; potem błąd w logu i w `error_message` |
| HTTP 4xx, niepoprawny JSON lub rekord | bez ponawiania; błąd w logu i w statusie |
| pusta odpowiedź (dane nieopublikowane) | bez ponawiania; status `no_data` lub `partial` z listą dób |
| błąd jednej doby | pozostałe doby są nadal pobierane |
| nieoczekiwany wyjątek (np. baza) | run oznaczony jako `failed`, wyjątek w logu (`logger.exception`) |

## Wycena taryfy dynamicznej

`DynamicMarketPricing` liczy cenę dla klienta według wzoru:

    (RCE [PLN/MWh] / 1000 + tariffs.markup_pln_kwh) × (1 + tariffs.vat_rate)

RCE to hurtowa cena energii netto. Taryfy G11 i G12 w bazie to ceny brutto „all-in”, więc bez
narzutu (dystrybucja, opłaty, marża sprzedawcy) porównanie byłoby mylące.

Narzut i VAT są częścią definicji taryfy, tak jak stawki G11/G12 w `tariff_rates`, więc są
kolumnami tabeli `tariffs` (puste dla taryf ze stałymi stawkami). Seed i migracja ustawiają
0.40 PLN/kWh i 23%. Zmiana to zwykły `UPDATE` na tabeli `tariffs`, bez deployu. 
Kilka taryf dynamicznych (np. różnych sprzedawców) może korzystać
z tych samych cen RCE, a różnić się narzutem.

Pozostałe zasady:

- Ceny kwadransów (`slot_prices[...].prices_by_day`) i rachunki liczymy przy każdym odczycie
  z bieżącego cennika i cen RCE, tak jak dla G11 i G12.
- Brak ceny dla kwadransu daje `null`.
- Rachunki taryf liczy silnik rachunku (ten sam co `/upload/calculation-details/{id}`): wszystkich taryf
  operatora `/energy-files/{id}/tariff-comparison`, a taryfy z profilu `/energy-files/{id}/data`
  (`tariffs=all` dodaje tam tylko ceny do wykresów pozostałych taryf). Brak ceny RCE dla któregokolwiek
  kwadransu daje ofercie dynamicznej `payable_gross = null` (w `/data` `estimated_cost_pln = null`)
  i powód w `note`, a ceny do wykresów mają tam `null`.
- Jeśli plik wgrano, zanim worker pobrał ceny dla jego okresu, koszty uzupełnią się same
  po pobraniu cen, bez ponownego importu.

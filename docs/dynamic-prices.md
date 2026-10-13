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

**`dynamic_price_observations`**: jedna obserwacja ceny.

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

- Codziennie o 15:00 Europe/Warsaw (`SYNC_HOUR` w workerze; PSE publikuje ceny na jutro ok. 13:45)
  uzupełnia brakujące lub niepełne doby z ostatnich `CATCHUP_DAYS` (7) dni oraz jutro.
- Przy starcie robi to samo, więc nadrabia przestój.
- Jeśli PSE jeszcze nie opublikowało jutra, kolejne uruchomienie dociągnie tę dobę w ramach okna catch-up.

```bash
python -m app.workers.price_sync_worker run                            # harmonogram
python -m app.workers.price_sync_worker once                           # jednorazowo uzupełnij braki
python -m app.workers.price_sync_worker backfill 2024-06-14 2025-12-31 # historia (paczki po 31 dni)
```

Bez Dockera ten sam efekt da cron: `0 15 * * * cd backend && python -m app.workers.price_sync_worker once`.

## Endpointy

| metoda | ścieżka | autoryzacja | opis |
|---|---|---|---|
| POST | `/api/v1/dynamic-prices/sync` | nagłówek `X-Admin-Key` | ręczna synchronizacja |
| GET | `/api/v1/dynamic-prices/sync/status` | JWT | ostatnie uruchomienie i ostatnie udane |
| GET | `/api/v1/dynamic-prices?business_date=RRRR-MM-DD` | JWT | ceny z doby (PLN/MWh i PLN/kWh) |
| GET | `/api/v1/dynamic-prices/history?from=&to=&resolution=` | JWT | historia cen do wykresu, średnia, kompletność dni |

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

- Ceny są zapisywane w wynikach symulacji w momencie importu (`slot_prices[...].prices_by_day`),
  podobnie jak ceny G11 i G12.
- Brak ceny dla kwadransu daje `null`.
- Wynik taryfy zawiera `price_coverage` (0–1) i `missing_price_intervals`.
- Koszt brakujących kwadransów jest ekstrapolowany średnią ceną z pokrytego zużycia.
  Przy zerowym pokryciu `estimated_cost_pln = null`.
- Przy łączeniu plików ceny dynamiczne są scalane po dniach ze wszystkich importów.
- Jeśli plik wgrano zanim worker pobrał ceny dla jego okresu, trzeba wgrać go ponownie,
  bo ceny są zapisywane w momencie importu.

# Kontrakt API Smart Home: backend ↔ hub ↔ urządzenie

Symulacja Smart Home składa się z trzech stron:

```
 backend (FastAPI)  ── HUB_URL, X-Hub-Api-Key ──▶  hub  ── porty 9101–9150 ──▶  mikroserwisy urządzeń
        ▲                                           │
        └──── webhook POST /api/v1/home/events ─────┘
```

- **backend** zna tylko hub. Wysyła rejestr urządzeń domu, odczytuje ich stan i wydaje polecenia.
- **hub** zarządza mikroserwisami urządzeń (uruchamia, przydziela porty, odpytuje) i jest
  jedynym źródłem czasu symulacji.
- **urządzenie** to sterownik jednego `device_id` na własnym porcie. Nie ma własnego zegara,
  czas dostaje od huba w `POST /tick`.

Klient po
stronie backendu: `backend/app/clients/hub_client.py`, modele: `backend/app/schemas/smart_home.py`.

Hub obsługuje **jeden dom** i nie zna użytkowników: `PUT /home/devices` nie ma `user_id`, a nowy
rejestr zastępuje poprzedni. Przypisanie domu do użytkownika należy do backendu
(`HUB_HOME_USER_EMAIL`).

### Zakres w czasie

| Element | Ten sprint | Kolejny sprint |
|---|---|---|
| Rejestr, stan i komendy (`/home/devices`) | ZP-83, komendy wykonywane od razu | `start_at` |
| API urządzenia, w tym `POST /tick` | ZP-84, tick wywołują testy | tick wysyła zegar huba |
| `HubClient` i kontrakt webhooka | ZP-54 | |
| Zegar `/home/clock` | | hub |
| Webhook `/api/v1/home/events` | | hub i backend |

Webhook czeka na zegar, bo zdarzenia powstają w tickach. Do tego czasu `sim_time` w
`GET /home/devices` ma wartość `null`.

## Zasady ogólne

| | |
|---|---|
| Format | JSON, `Content-Type: application/json`, kodowanie UTF-8 |
| Czas | ISO 8601 **z przesunięciem strefy**, np. `2026-10-19T09:30:00+02:00`; ziarnistość 15 min jak w pliku urządzeń |
| Czas symulacji | Pola `sim_time` to czas symulowanego domu, nie zegar ściany. Jedyne źródło: hub. Czasy porównuje się i odejmuje jako momenty (UTC), nigdy po godzinie lokalnej, dzięki czemu doba ze zmianą czasu liczy się poprawnie |
| Identyfikatory | `device_id` i `program_id` jak w [pliku urządzeń](devices-file-format.md) |
| Energia, moc | `*_kwh` w kWh, `*_kw` w kW; ujemne wartości tylko dla kategorii `OZE` (produkcja) |
| Nieznane pola | Ignorowane przez odbiorcę, żeby kontrakt można było rozszerzać |
| Błędy | Status HTTP + `{"detail": "opis dla człowieka", "code": "kod_maszynowy"}` |
| Walidacja danych | Reguły pliku urządzeń (np. dodatnia moc, ujemna energia tylko dla `OZE`) sprawdza backend przy imporcie. Hub i urządzenia sprawdzają tylko to, czego potrzebują do pracy: kształt danych i zgodność profilu z `duration_min` |

### Uwierzytelnianie

- Backend → hub i hub → backend: nagłówek `X-Hub-Api-Key: <HUB_API_KEY>`. Ten sam klucz po
  obu stronach, konfigurowany w `.env`. Brak lub błędny klucz: `401 {"code": "invalid_api_key"}`.
- Hub → urządzenie: bez klucza, ochroną jest brak dostępu z zewnątrz (patrz niżej).

### Dostęp do urządzeń

Wszyscy klienci, w tym backend, rozmawiają wyłącznie z hubem. Bezpośredni dostęp do urządzenia
jest poza kontraktem i służy tylko do demonstracji i debugowania.

| | Tryb domyślny | Tryb demo |
|---|---|---|
| Uruchomienie | `docker compose up` | dodatkowo `-f docker-compose.demo.yml` |
| Nasłuch urządzeń (`DEVICE_BIND_HOST`) | `127.0.0.1` | `0.0.0.0` |
| Porty na hoście | brak | `127.0.0.1:9101-9150:9101-9150` |
| Kto dosięgnie urządzeń | tylko hub | hub, przeglądarka na tym komputerze, kontenery z tej sieci |

Proces nasłuchujący na `127.0.0.1` w kontenerze jest niewidoczny z hosta nawet po wystawieniu
portu, dlatego tryb demo musi zmienić oba ustawienia. O stanie decyduje urządzenie, a hub czyta
go z `GET /status`, więc komenda wysłana bezpośrednio w demo nie rozsynchronizuje huba.

### Porty urządzeń

- Hub przydziela porty kolejno z puli **9101–9150**, pierwszy wolny. Po wyczerpaniu puli
  `PUT /home/devices` zwraca `409 port_pool_exhausted` i nie zmienia działających urządzeń.
- Port jest **stały dla danego `device_id`**: hub zapisuje mapowanie `device_id → port` trwale
  i po restarcie albo ponownym `PUT /home/devices` urządzenie dostaje ten sam port.
- Port zwalnia dopiero usunięcie urządzenia z rejestru.

### Czas symulacji

- Urządzenie liczy stan (postęp programu, energię) wyłącznie na podstawie `sim_time` z ticka.
  Nie używa `datetime.now()`.
- Akcja zaczyna się w czasie ostatniego ticka, a przed pierwszym tickiem w czasie pierwszego ticka.
- Krok ticka jest dowolny: urządzenie musi poprawnie policzyć każdy dodatni krok, także
  dwugodzinny. Hub będzie tykał co 15 minut czasu symulacji.
- Pierwszy tick ustawia tylko punkt odniesienia i nie nalicza energii.

### Kody błędów

| HTTP | `code` | Kiedy |
|---|---|---|
| 400 | `invalid_request` | Niepoprawne JSON albo brak wymaganego pola |
| 401 | `invalid_api_key` | Brak albo błędny `X-Hub-Api-Key` |
| 404 | `device_not_found` | `device_id` spoza rejestru |
| 404 | `program_not_found` | `program_id` spoza programów urządzenia |
| 409 | `invalid_state` | Polecenie niemożliwe w obecnym stanie (np. start programu, gdy inny trwa) |
| 409 | `stale_tick` | `sim_time` ticka wcześniejszy niż ostatni |
| 409 | `config_requires_restart` | `PUT /config` zmienia pole inne niż nazwa lub kategoria |
| 409 | `port_pool_exhausted` | Rejestr nie mieści się w puli portów 9101–9150 |
| 422 | `validation_error` | Dane poprawne składniowo, ale łamią reguły kontraktu (np. profil niezgodny z `duration_min`, powtórzony `device_id`) |
| 422 | `start_at_not_supported` | `start_at` w komendzie, dopóki hub nie ma zegara |
| 502 | `device_unreachable` | Hub nie dostał odpowiedzi od mikroserwisu urządzenia |

## 1. Backend → hub

Bazowy adres: `HUB_URL` (`http://hub:9100` w docker-compose). Wszystkie żądania z `X-Hub-Api-Key`.

### `PUT /home/devices` – rejestr urządzeń domu

Pełny rejestr domu, w tym samym kształcie co `devices` w pliku urządzeń. Semantyka **zastąpienia**:

- nowe `device_id` – hub uruchamia mikroserwis i przydziela port,
- zmiana typu, mocy, programów albo `flexibility` – hub restartuje mikroserwis na tym samym
  porcie; restart kasuje stan urządzenia, w tym trwający program i liczniki energii,
- zmiana tylko nazwy albo kategorii – hub wywołuje `PUT /config` bez restartu,
- bez zmian – mikroserwis działa dalej bez przerwy,
- brakujące w żądaniu – hub zatrzymuje mikroserwis i usuwa urządzenie z rejestru.

Żądanie:

```json
{
  "devices": [
    {
      "device_id": "dev_wm_01",
      "device_name": "Pralka Bosch",
      "device_type": "washing_machine",
      "device_category": "AGD",
      "flexibility": {
        "mode": "shiftable",
        "allowed_window": { "from": "07:00", "to": "22:00" }
      },
      "programs": [
        {
          "program_id": "cotton_60",
          "program_name": "Bawełna 60°C",
          "duration_min": 120,
          "profile_kwh": [0.45, 0.45, 0.3, 0.1, 0.1, 0.15, 0.2, 0.2]
        }
      ]
    }
  ]
}
```

Odpowiedź `200`:

```json
{
  "devices": [
    { "device_id": "dev_wm_01", "port": 9101, "state": "off" }
  ]
}
```

Pusta lista `devices` usuwa wszystkie urządzenia. Pola opcjonalne mogą nie wystąpić albo mieć
wartość `null`; urządzenie z programami może nie mieć `max_power_kw`. Hub odpowiada dopiero po
uruchomieniu mikroserwisów (każdy odpowiada na `GET /health`), dlatego `HubClient` używa dla tego
żądania dłuższego timeoutu (60 s).

### `GET /home/devices` – stan urządzeń

Odpowiedź `200`:

```json
{
  "sim_time": "2026-10-19T09:45:00+02:00",
  "devices": [
    {
      "device_id": "dev_wm_01",
      "device_name": "Pralka Bosch",
      "port": 9101,
      "state": "running",
      "program_id": "cotton_60",
      "program_started_at": "2026-10-19T09:30:00+02:00",
      "program_ends_at": "2026-10-19T11:30:00+02:00",
      "power_kw": 1.8,
      "energy_kwh": 0.45
    }
  ]
}
```

| Pole | Opis |
|---|---|
| `state` | `off`, `idle` (włączone, nic nie robi), `running` (pracuje / program trwa), `error`, `unreachable` (hub nie dostał odpowiedzi od mikroserwisu) |
| `program_id`, `program_started_at`, `program_ends_at` | Trwający program; `null`, gdy brak |
| `power_kw` | Bieżąca moc (średnia w obecnym kwadransie), ujemna dla produkcji PV; `null` przy `unreachable` |
| `energy_kwh` | Zużycie narastająco od startu mikroserwisu; `null` przy `unreachable` |

Stan `error` oznacza, że hub wyczerpał limit restartów urządzenia.

`energy_kwh` służy tylko do podglądu: restart mikroserwisu (np. po zmianie programów w rejestrze)
zeruje licznik. Zużycie do obliczeń backend bierze ze zdarzeń `energy_report` i `device_finished`
z webhooka.

### `POST /home/devices/{device_id}/commands` – polecenie dla urządzenia

```json
{ "command": "on" }
{ "command": "off" }
{ "command": "start_program", "program_id": "cotton_60", "start_at": "2026-10-19T13:00:00+02:00" }
```

| Pole | Opis |
|---|---|
| `command` | `on`, `off`, `start_program` |
| `program_id` | Wymagane przy `start_program`, niedozwolone przy pozostałych |
| `start_at` | Tylko `start_program`, pole opcjonalne: czas symulacji startu, pełny kwadrans. Brak = od razu. Hub przechowuje zaplanowany start i wysyła `POST /programs/{program_id}/start`, gdy zegar osiągnie `start_at`: najpierw tick z `sim_time = start_at`, potem start, bo akcja zaczyna się w czasie ostatniego ticka. Do czasu wdrożenia zegara hub odrzuca to pole kodem `422 start_at_not_supported`, zamiast po cichu startować od razu |

Odpowiedź `202`:

```json
{
  "command_id": "cmd_7f3a2c",
  "device_id": "dev_wm_01",
  "status": "accepted",
  "state": "idle"
}
```

`status`: `accepted` (wykonane albo przekazane do urządzenia), `scheduled` (start w przyszłości).
`off` w trakcie programu przerywa go, a akcja kończy się z `interrupted: true` i energią do tego
momentu. Błędy: `404 device_not_found`, `404 program_not_found`, `409 invalid_state`,
`422 start_at_not_supported`, `502 device_unreachable`.

### `GET /home/clock`, `PUT /home/clock` – zegar symulacji (kolejny sprint)

```json
{ "sim_time": "2026-10-19T09:45:00+02:00", "running": true, "speed": 60.0 }
```

`PUT` przyjmuje dowolny podzbiór pól: `sim_time` (ustawienie czasu, tylko gdy zegar stoi),
`running` (`true` start, `false` pauza), `speed` (ile sekund symulacji na sekundę rzeczywistą,
`> 0`). Odpowiedź `200` z pełnym stanem zegara.

## 2. Hub → urządzenie

Bazowy adres: `http://127.0.0.1:{port}`. Każdy mikroserwis obsługuje jedno urządzenie.

### Uruchomienie mikroserwisu

Hub zapisuje konfigurację do pliku JSON i startuje proces poleceniem
`python -m device --config <plik>`. Plik to obiekt urządzenia jak w `PUT /home/devices` oraz:

| Pole | Opis |
|---|---|
| `port` | Port z mapy `device_id → port` |
| `bind_host` | Adres nasłuchu, wartość `DEVICE_BIND_HOST` huba |

Plik, a nie zmienne środowiskowe, bo listy programów z profilami nie mieszczą się wygodnie w env.

### Endpointy

| Metoda i ścieżka | Opis | Odpowiedź |
|---|---|---|
| `GET /health` | Czy mikroserwis żyje | `200 {"status": "ok", "device_id": "dev_wm_01"}` |
| `GET /config` | Bieżąca konfiguracja | `200` – obiekt urządzenia jak w `PUT /home/devices` |
| `PUT /config` | Zmiana `device_name` lub `device_category` bez restartu | `200` – zapisana konfiguracja; `409 config_requires_restart` dla innych pól |
| `GET /status` | Stan urządzenia | `200` – patrz niżej |
| `POST /on` | Włączenie | `200` – stan; `409 invalid_state`, gdy trwa program |
| `POST /off` | Wyłączenie, kończy akcję | `200` – stan |
| `POST /programs/{program_id}/start` | Start programu | `200` – stan; `404 program_not_found`, `409 invalid_state` |
| `GET /energy` | Zużycie energii | `200` – patrz niżej |
| `POST /tick` | Krok czasu symulacji od huba | `200` – patrz niżej; `409 stale_tick`; `422 validation_error` dla czasu bez strefy |

### Zachowanie urządzenia

Urządzenie startuje w stanie `off`.

| Urządzenie | `POST /on` | `POST /off` |
|---|---|---|
| Z programami | `idle`, czeka na program | `off`, przerywa program |
| Bez programów (w tym EV, pompa ciepła) | `running` z mocą `max_power_kw` | `off`, kończy akcję |
| PV | `running`, stała produkcja `-max_power_kw` | `off`, kończy akcję |

- `POST /programs/.../start` na urządzeniu w stanie `off` najpierw je włącza. Program pracuje
  według `profile_kwh` i kończy się po `duration_min`, a urządzenie wraca do `idle`.
- Wstrzymanie ładowania EV to `POST /off`, a wznowienie to `POST /on`. Każdy odcinek jest osobną
  akcją, a energia sumuje się w `total_kwh`.
- Moc programu w kwadransie to wartość z profilu podzielona przez 0,25 h. Urządzenie bez programów
  zużywa w kwadransie najwyżej `max_power_kw × 0,25 h`.
- PV produkuje stale `-max_power_kw` niezależnie od pory dnia. To uproszczenie na ten sprint;
  realistyczna produkcja (krzywa dobowa albo profil z akcji PV z pliku urządzeń) wejdzie razem
  z zegarem symulacji.

### `GET /status`

```json
{
  "device_id": "dev_wm_01",
  "state": "running",
  "program_id": "cotton_60",
  "program_started_at": "2026-10-19T09:30:00+02:00",
  "program_ends_at": "2026-10-19T11:30:00+02:00",
  "power_kw": 1.8,
  "energy_kwh": 0.45,
  "sim_time": "2026-10-19T09:45:00+02:00"
}
```

`sim_time` to czas ostatniego ticka (`null` przed pierwszym).

### `GET /energy`

```json
{
  "device_id": "dev_wm_01",
  "total_kwh": 1.95,
  "last_action": {
    "program_id": "cotton_60",
    "started_at": "2026-10-19T09:30:00+02:00",
    "ended_at": "2026-10-19T11:30:00+02:00",
    "energy_kwh": 1.95,
    "interrupted": false
  }
}
```

`total_kwh` to energia od startu mikroserwisu, ujemna dla PV. `last_action` to ostatnia
zakończona akcja (`null`, gdy żadnej nie było); `program_id` ma wartość `null` dla urządzeń bez
programów.

### `POST /tick`

Żądanie:

```json
{ "sim_time": "2026-10-19T09:45:00+02:00" }
```

Urządzenie przelicza pracę od poprzedniego ticka i odpowiada stanem oraz zdarzeniami od
poprzedniego ticka, także tymi z komend wykonanych między tickami:

```json
{
  "device_id": "dev_wm_01",
  "state": "running",
  "power_kw": 1.8,
  "energy_kwh": 0.45,
  "events": [
    { "type": "device_started", "sim_time": "2026-10-19T09:30:00+02:00", "data": { "program_id": "cotton_60" } }
  ]
}
```

`energy_kwh` w odpowiedzi ticka to energia **tego kroku**, a w `GET /status` wartość narastająca.

- Tick ze `sim_time` równym ostatniemu niczego nie zmienia (`200`, zerowa energia, puste `events`),
  dzięki czemu hub może go bezpiecznie ponowić.
- Tick ze `sim_time` wcześniejszym niż ostatni jest odrzucany (`409 stale_tick`), bo cofnięcie
  czasu popsułoby naliczanie energii.

## 3. Hub → backend: webhook zdarzeń

Wdrożenie w kolejnym sprincie, razem z zegarem. Urządzenia nie wysyłają niczego same: hub zbiera
zdarzenia z odpowiedzi na `POST /tick` i wysyła je partiami, co najmniej raz na tick, w którym coś
zaszło. Urządzenie zwraca `device_started` i `device_finished`, a `energy_report` i `device_error`
tworzy hub, odpowiednio z `energy_kwh` ticka i z własnego health-checku.

`POST {BACKEND_URL}/api/v1/home/events` z `X-Hub-Api-Key`:

```json
{
  "events": [
    {
      "event_id": "evt_000123",
      "type": "device_started",
      "device_id": "dev_wm_01",
      "sim_time": "2026-10-19T09:30:00+02:00",
      "data": { "program_id": "cotton_60", "command_id": "cmd_7f3a2c" }
    },
    {
      "event_id": "evt_000124",
      "type": "device_finished",
      "device_id": "dev_wm_01",
      "sim_time": "2026-10-19T11:30:00+02:00",
      "data": {
        "program_id": "cotton_60",
        "started_at": "2026-10-19T09:30:00+02:00",
        "energy_kwh": 1.95,
        "interrupted": false
      }
    },
    {
      "event_id": "evt_000125",
      "type": "energy_report",
      "device_id": "dev_fr_01",
      "sim_time": "2026-10-19T09:45:00+02:00",
      "data": { "interval_start": "2026-10-19T09:30:00+02:00", "energy_kwh": 0.03 }
    },
    {
      "event_id": "evt_000126",
      "type": "device_error",
      "device_id": "dev_dw_01",
      "sim_time": "2026-10-19T09:45:00+02:00",
      "data": { "code": "device_unreachable", "message": "Brak odpowiedzi na /tick" }
    }
  ]
}
```

| `type` | Kiedy | `data` |
|---|---|---|
| `device_started` | Urządzenie zaczęło pracę / program | `program_id` (albo `null`), `command_id` (gdy start z polecenia) |
| `device_finished` | Koniec programu albo wyłączenie w trakcie | `program_id`, `started_at`, `energy_kwh` cyklu, `interrupted` |
| `energy_report` | Co kwadrans dla każdego pracującego urządzenia | `interval_start`, `energy_kwh` |
| `device_error` | Urządzenie nie odpowiada albo wyczerpano limit restartów | `code`, `message` |

Odpowiedź backendu: `202 {"accepted": 4}`. `event_id` jest unikalny w obrębie huba; backend
ignoruje zdarzenia, które już zapisał, więc hub przy błędzie (timeout, 5xx) ponawia całą partię.
Na `401` hub nie ponawia i loguje błąd konfiguracji.

## Konfiguracja

| Zmienna | Strona | Opis |
|---|---|---|
| `HUB_URL` | backend | Adres huba, w docker-compose `http://hub:9100`; pusty = Smart Home wyłączony |
| `HUB_API_KEY` | backend, hub | Wspólny klucz `X-Hub-Api-Key` |
| `HUB_TIMEOUT_SECONDS` | backend | Timeout żądań do huba, domyślnie 5 s |
| `HUB_HOME_USER_EMAIL` | backend | Użytkownik, do którego należy dom huba; wchodzi razem z webhookiem |
| `BACKEND_URL` | hub | Adres backendu dla webhooka, np. `http://backend:8000` |
| `DEVICE_BIND_HOST` | hub | Adres nasłuchu urządzeń: `127.0.0.1` domyślnie, `0.0.0.0` w trybie demo |
| `HUB_STATE_DIR` | hub | Katalog pliku stanu i konfiguracji urządzeń, domyślnie `/data` |
| `HUB_HEALTH_INTERVAL_SECONDS` | hub | Co ile sekund hub sprawdza urządzenia, domyślnie 5 |

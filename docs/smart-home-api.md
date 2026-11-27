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
(`HUB_HOME_USER_EMAIL`, [sekcja 4](#4-frontend--backend-dom-właściciela)).

### Zakres w czasie

| Element | Stan |
|---|---|
| Rejestr, stan i komendy (`/home/devices`) | ZP-83, `start_at` ZP-94 |
| API urządzenia, w tym `POST /tick` | ZP-84 |
| `HubClient` i kontrakt webhooka | ZP-54 |
| Dom właściciela, `/api/v1/home`, wysyłka rejestru | ZP-93 |
| Zegar `/home/clock` | ZP-94, `simulation_id` ZP-95 |
| Webhook `/api/v1/home/events`, stan domu `/api/v1/home/state` | ZP-95 |
| Ekran „Mój dom”, sterowanie urządzeniami i zegarem przez backend, opis urządzeń w stanie | ZP-97 |
| Przebieg z własnym profilem (`POST /run`, `run_profile`), `restart` zegara | ZP-96 |
| Komendy wsadowe (`POST /home/commands`, `DELETE /home/commands`), `stop_at` zegara, wykonanie planu dnia z PV z dnia referencyjnego (`/api/v1/home/plan-runs`) | ZP-113 |
| Rachunek przed i po planie w przebiegu (`cost`), historia przebiegów | ZP-114 |
| Pomieszczenie urządzenia (`room`) w rejestrze i w stanie domu | ZP-109 |
| Bilans stanu domu w przebiegu planu liczony od jego początku (`today.period`, `today.plan_date`) | ZP-110 |

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
  Hub wysyła tick z bieżącym czasem zaraz po uruchomieniu mikroserwisu, więc komenda przed kolejnym
  krokiem zegara zaczyna się w bieżącym czasie symulacji.
- Krok ticka jest dowolny: urządzenie musi poprawnie policzyć każdy dodatni krok, także
  dwugodzinny. Hub tyka co 15 minut czasu symulacji.
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
| 409 | `config_requires_restart` | `PUT /config` zmienia pole inne niż nazwa, kategoria lub pomieszczenie |
| 409 | `port_pool_exhausted` | Rejestr nie mieści się w puli portów 9101–9150 |
| 409 | `clock_running` | Zmiana `sim_time`, gdy zegar działa |
| 422 | `validation_error` | Dane poprawne składniowo, ale łamią reguły kontraktu (np. profil niezgodny z `duration_min`, powtórzony `device_id`, czas bez strefy albo poza pełnym kwadransem) |
| 422 | `start_at_in_past` | `start_at` wcześniejszy niż bieżący czas symulacji |
| 422 | `stop_at_in_past` | `stop_at` zegara nie później niż czas symulacji |
| 502 | `device_unreachable` | Hub nie dostał odpowiedzi od mikroserwisu urządzenia |

## 1. Backend → hub

Bazowy adres: `HUB_URL` (`http://hub:9100` w docker-compose). Wszystkie żądania z `X-Hub-Api-Key`.

### `PUT /home/devices` – rejestr urządzeń domu

Pełny rejestr domu, w tym samym kształcie co `devices` w pliku urządzeń. Backend zawsze podaje `room`:
pomieszczenie z pliku albo domyślne według typu (ZP-109); hub je przechowuje, a na pracę urządzenia nie wpływa.
Hub przyjmuje tylko pomieszczenia ze słownika `room` (`docs/devices-file-format.md`), inne odrzuca `400 invalid_request`.
Semantyka **zastąpienia**:

- nowe `device_id` – hub uruchamia mikroserwis i przydziela port,
- zmiana typu, mocy, programów albo `flexibility` – hub restartuje mikroserwis na tym samym
  porcie; restart kasuje stan urządzenia, w tym trwający program i liczniki energii,
- zmiana tylko nazwy, kategorii albo pomieszczenia – hub wywołuje `PUT /config` bez restartu,
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
      "room": "bathroom",
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
| `run` | Trwający przebieg z własnym profilem (`run_profile`): `ref`, `started_at`, `ends_at`; `null`, gdy brak |
| `power_kw` | Bieżąca moc (średnia w obecnym kwadransie), ujemna dla produkcji PV; `null` przy `unreachable` |
| `energy_kwh` | Zużycie narastająco od startu mikroserwisu; `null` przy `unreachable` |

Stan `error` oznacza, że hub wyczerpał limit restartów urządzenia.

`energy_kwh` służy tylko do podglądu: restart mikroserwisu (np. po zmianie programów w rejestrze)
zeruje licznik. Zużycie do obliczeń backend bierze ze zdarzeń `energy_report` z webhooka
([sekcja 3](#3-hub--backend-webhook-zdarzeń)).

### `POST /home/devices/{device_id}/commands` – polecenie dla urządzenia

```json
{ "command": "on" }
{ "command": "off" }
{ "command": "start_program", "program_id": "cotton_60", "start_at": "2026-10-19T13:00:00+02:00" }
{ "command": "run_profile", "profile_kwh": [0.01, 0.015, 0.015, 0.01], "ref": "act_0016", "start_at": "2026-10-19T18:00:00+02:00" }
```

| Pole | Opis |
|---|---|
| `command` | `on`, `off`, `start_program`, `run_profile` |
| `program_id` | Wymagane przy `start_program`, niedozwolone przy pozostałych |
| `profile_kwh` | Wymagane przy `run_profile`, niedozwolone przy pozostałych: energia w kolejnych kwadransach (1–672, czyli do tygodnia), ujemna dla produkcji PV. Hub przekazuje je do `POST /run` urządzenia |
| `ref` | Tylko `run_profile`, opcjonalne (1–100 znaków): identyfikator akcji, którą wykonuje przebieg (np. akcji planu). Wraca w zdarzeniach `device_started` i `device_finished` |
| `start_at` | Tylko `start_program` i `run_profile`, pole opcjonalne: czas symulacji startu, pełny kwadrans ze strefą. Brak albo czas równy bieżącemu = od razu. Hub przechowuje zaplanowany start i wysyła go do urządzenia, gdy zegar osiągnie `start_at`: najpierw tick z `sim_time = start_at`, potem start, bo akcja zaczyna się w czasie ostatniego ticka. Przebieg kończący się o `start_at` kolejnego kończy się w tym samym ticku, więc sąsiednie akcje idą jedna po drugiej |

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
`422 start_at_in_past`, `422 validation_error`, `502 device_unreachable`.

Komenda `scheduled` nie ma jeszcze wyniku. Jeśli w chwili `start_at` urządzenie nie wykona jej (np.
trwa inny program albo nie odpowiada), hub zapisuje zdarzenie `device_error` z kodem błędu i nie
ponawia komendy. Usunięcie urządzenia z rejestru kasuje jego zaplanowane komendy.

### `POST /home/commands` – wiele komend jednym żądaniem

Komendy z treścią jak w `POST /home/devices/{device_id}/commands`, z `device_id` w każdej. Backend
wysyła tak całą dobę planu: jego pozycje i historię dnia referencyjnego (np. produkcję PV).

```json
{ "commands": [
  { "device_id": "dev_wm_01", "command": "start_program", "program_id": "cotton_60", "start_at": "2026-10-19T13:00:00+02:00" },
  { "device_id": "dev_ev_01", "command": "run_profile", "profile_kwh": [0.9, 0.0, 0.925], "start_at": "2026-10-19T01:00:00+02:00" },
  { "device_id": "dev_xx_09", "command": "on" }
] }
```

Odpowiedź `200` z wynikiem każdej komendy w kolejności żądania:

```json
{ "results": [
  { "device_id": "dev_wm_01", "command_id": "cmd_7f3a2c", "status": "scheduled" },
  { "device_id": "dev_ev_01", "command_id": "cmd_91be04", "status": "scheduled" },
  { "device_id": "dev_xx_09", "status": "rejected", "code": "device_not_found", "detail": "Nie ma urządzenia 'dev_xx_09' w rejestrze" }
] }
```

- `status`: `accepted` i `scheduled` jak przy pojedynczej komendzie, `rejected` z `code` i `detail`
  błędu tej komendy (`device_not_found`, `program_not_found`, `start_at_in_past`, `invalid_state`,
  `device_unreachable`…). Odrzucenie jednej komendy nie zatrzymuje pozostałych.
- Hub obsługuje całą partię pod jedną blokadą zegara: wszystkie komendy widzą ten sam czas symulacji,
  a tick nie wypada w połowie partii.
- Komendy „teraz” idą do urządzeń równolegle, a komendy jednego urządzenia po kolei, w kolejności
  z żądania (np. `on`, potem `off`).
- Partia ma od 1 do 1000 komend. Komenda łamiąca reguły kontraktu (np. `start_at` przy `on`) to błąd
  całej partii: `422 validation_error` (brak `device_id` albo zły typ: `400 invalid_request`), a hub nie
  wykonuje z niej niczego.
- Odpowiedź nie podaje stanu urządzeń (`state`): po partii backend odczytuje go z `GET /home/devices`.

### `DELETE /home/commands` – skasowanie zaplanowanych komend

Kasuje wszystkie komendy czekające na `start_at` (pod blokadą zegara, więc żadna nie wystartuje
w trakcie) i odpowiada `200` z ich liczbą: `{ "cancelled": 12 }`. To, co urządzenia już wykonują
(program, przebieg, praca po `on`), trwa dalej; zegar, urządzenia i `simulation_id` zostają bez zmian.
Powtórzenie jest bezpieczne (`{ "cancelled": 0 }`). Backend wysyła je przy „Zakończ” planu dnia.

### `GET /home/clock`, `PUT /home/clock` – zegar symulacji

```json
{ "sim_time": "2026-10-19T09:45:00+02:00", "running": true, "speed": 288.0, "stop_at": null, "simulation_id": "sim_4f1c…" }
```

`PUT` przyjmuje dowolny podzbiór pól `sim_time`, `running`, `speed`, `stop_at`, a do tego `restart`. Odpowiedź `200` z pełnym stanem zegara.

| Pole | Opis |
|---|---|
| `sim_time` | Bieżący czas symulacji w strefie domu (`Europe/Warsaw`), pełny kwadrans z lat 1970–2100. W `PUT` dowolna strefa, tylko gdy zegar stoi; inaczej `409 clock_running` |
| `restart` | Tylko w `PUT`, opcjonalne, wymaga `sim_time`: `true` zaczyna nową symulację także przy czasie równym bieżącemu. Backend wysyła je przy każdym ustawieniu doby, więc ta sama doba drugi raz też zaczyna od wyłączonych urządzeń i pustej kolejki |
| `running` | `true` start, `false` pauza. Pauza zatrzymuje ticki, więc energia przestaje rosnąć |
| `speed` | Ile sekund symulacji na sekundę rzeczywistą, `> 0`. Doba w 5 minut to `288` (domyślnie) |
| `stop_at` | Chwila, w której zegar sam stanie: w ticku, który do niej dojdzie, `running` zmienia się na `false`, a `stop_at` na `null`. Pełny kwadrans ze strefą, późniejszy niż czas symulacji (po zmianie `sim_time` w tym samym `PUT`: niż nowy czas), inaczej `422 stop_at_in_past`. W `PUT` `null` kasuje zatrzymanie, a brak pola zostawia je bez zmian. Nowa symulacja (`sim_time`) zawsze je kasuje. Backend ustawia je na koniec planu dnia |
| `simulation_id` | Tylko do odczytu. Identyfikator przebiegu symulacji: nowy po każdym ustawieniu `sim_time` i po restarcie huba. Niosą go zdarzenia webhooka, więc dwa przebiegi tej samej doby się nie sumują |

Hub startuje z zatrzymanym zegarem ustawionym na północ bieżącego dnia. Zegar i zaplanowane komendy
są tylko w pamięci, więc restart huba ustawia je od nowa.

**Ustawienie `sim_time` zaczyna nową symulację**: hub wysyła urządzeniom `POST /reset` i kasuje
zaplanowane komendy. Dzięki temu tę samą dobę można puścić drugi raz, także po cofnięciu zegara.
Dlatego kolejność jest stała: najpierw `sim_time`, potem komendy ze `start_at`, na końcu
`running: true`. `PUT` z czasem równym bieżącemu niczego nie zmienia, więc można go ponawiać;
z `restart: true` zaczyna nową symulację mimo to.

Gdy któreś urządzenie nie wykona resetu, `PUT` zwraca `502 device_unreachable`, a czas, `running`,
`speed` i zaplanowane komendy zostają bez zmian. Urządzenia, które zdążyły się zresetować, tracą
swój stan, więc `PUT` trzeba ponowić. Urządzenia w stanie `error` są pomijane.

Zegar przesuwa czas krokami po 15 minut w UTC, dlatego doba ze zmianą czasu ma 92 albo 100
kwadransów. Zmiana tempa i pauza nie gubią zaplanowanych komend ani rozpoczętego kroku. Czas ticka
wlicza się w krok, ale kolejny krok zaczyna się dopiero po odpowiedziach urządzeń, więc tempo jest
górną granicą: gdy tick trwa dłużej niż krok, zegar zwalnia i niczego nie nadrabia, a żaden kwadrans
nie jest pomijany. Urządzenie, które nie odpowiada, nie wstrzymuje
ticka pozostałych; hub zapisuje dla niego `device_error`, a urządzenia w stanie `error` pomija.

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
| `PUT /config` | Zmiana `device_name`, `device_category` lub `room` bez restartu | `200` – zapisana konfiguracja; `409 config_requires_restart` dla innych pól; `422 validation_error` dla `room` spoza słownika |
| `GET /status` | Stan urządzenia | `200` – patrz niżej |
| `POST /on` | Włączenie | `200` – stan; `409 invalid_state`, gdy trwa program |
| `POST /off` | Wyłączenie, kończy akcję | `200` – stan |
| `POST /programs/{program_id}/start` | Start programu | `200` – stan; `404 program_not_found`, `409 invalid_state` |
| `POST /run` | Przebieg z własnym profilem: `{"profile_kwh": [...], "command_id": "…", "ref": "…"}` | `200` – stan; `409 invalid_state`, gdy trwa program albo inny przebieg; `400 invalid_request` dla pustego lub zbyt długiego profilu |
| `POST /reset` | Powrót do stanu po uruchomieniu: `off`, zerowe liczniki, brak czasu symulacji i zdarzeń | `200` – stan |
| `GET /energy` | Zużycie energii | `200` – patrz niżej |
| `POST /tick` | Krok czasu symulacji od huba | `200` – patrz niżej; `409 stale_tick`; `422 validation_error` dla czasu bez strefy |

`POST /on` i `POST /programs/{program_id}/start` przyjmują opcjonalną treść `{"command_id": "cmd_7f3a2c"}`.
Hub podaje w niej identyfikator polecenia, a urządzenie zwraca go w `data.command_id` zdarzenia
`device_started` tej akcji (`null`, gdy akcję zaczęto bez `command_id`). `POST /run` ma `command_id`
i `ref` w swojej treści; `ref` wraca w `data.ref` zdarzeń `device_started` i `device_finished`
(`null` dla akcji spoza przebiegu, np. ręcznego włączenia).

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
- PV po `POST /on` produkuje stale `-max_power_kw`. Realistyczną produkcję daje przebieg
  `POST /run` z profilem produkcji (ujemne wartości).
- `POST /run` służy akcjom bez programu, które mają własny profil: ładowanie EV z przerwami, grzanie
  bojlera albo pompy ciepła w wybranych kwadransach, produkcja PV. Pracuje według `profile_kwh` (moc w kwadransie: wartość z profilu przez 0,25 h, ze
  znakiem z profilu) i kończy się po ostatnim kwadransie. Urządzenie bez programów wraca wtedy do
  `off`, a z programami do `idle`.
- Przebieg przejmuje pracę stałą mocą po `POST /on`: tamta akcja kończy się (`interrupted: false`),
  a zaczyna przebieg. Program albo inny przebieg blokują `POST /run` (`409 invalid_state`), a w trakcie
  przebiegu `POST /on` i start programu też dostają `409`. `POST /off` przerywa przebieg
  (`interrupted: true`, energia do tej chwili).

### `GET /status`

```json
{
  "device_id": "dev_wm_01",
  "state": "running",
  "program_id": "cotton_60",
  "program_started_at": "2026-10-19T09:30:00+02:00",
  "program_ends_at": "2026-10-19T11:30:00+02:00",
  "run": null,
  "power_kw": 1.8,
  "energy_kwh": 0.45,
  "sim_time": "2026-10-19T09:45:00+02:00"
}
```

`sim_time` to czas ostatniego ticka (`null` przed pierwszym). `run` opisuje trwający przebieg
z `POST /run`: `{"ref": "act_0016", "started_at": "…", "ends_at": "…"}`, a poza nim ma `null`.

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
  "interval_start": "2026-10-19T09:30:00+02:00",
  "events": [
    {
      "type": "device_started",
      "sim_time": "2026-10-19T09:30:00+02:00",
      "data": { "program_id": "cotton_60", "command_id": "cmd_7f3a2c" }
    }
  ]
}
```

`energy_kwh` w odpowiedzi ticka to energia **tego kroku**, a w `GET /status` wartość narastająca.
`interval_start` to początek kroku, czyli czas poprzedniego ticka urządzenia (`null` przy pierwszym ticku).
Zwykle to kwadrans przed `sim_time`, ale urządzenie, które nie dostało ticka, liczy dłuższy krok.
Suma `energy_kwh` z ticków równa się `total_kwh`.

- Tick ze `sim_time` równym ostatniemu niczego nie zmienia (`200`, zerowa energia, puste `events`),
  dzięki czemu hub może go bezpiecznie ponowić.
- Tick ze `sim_time` wcześniejszym niż ostatni jest odrzucany (`409 stale_tick`), bo cofnięcie
  czasu popsułoby naliczanie energii.

## 3. Hub → backend: webhook zdarzeń

Urządzenia nie wysyłają niczego same: hub zbiera zdarzenia z odpowiedzi na `POST /tick` i wysyła je
do backendu jedną partią na tick, w którym coś zaszło. Urządzenie zwraca `device_started` i
`device_finished`, a `energy_report` i `device_error` tworzy hub: pierwsze z `energy_kwh` i
`interval_start` ticka, drugie z nieudanego ticka, nieudanej zaplanowanej komendy albo health-checku.

`POST {BACKEND_URL}/api/v1/home/events` z `X-Hub-Api-Key`:

```json
{
  "events": [
    {
      "event_id": "evt_6a1f0c9e4b2d4c7e8f3a5b1c2d3e4f50",
      "simulation_id": "sim_4f1c2b7a9d8e4f6a8b0c1d2e3f405162",
      "type": "device_started",
      "device_id": "dev_wm_01",
      "sim_time": "2026-10-19T09:30:00+02:00",
      "data": { "program_id": "cotton_60", "command_id": "cmd_7f3a2c" }
    },
    {
      "event_id": "evt_…",
      "simulation_id": "sim_4f1c…",
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
      "event_id": "evt_…",
      "simulation_id": "sim_4f1c…",
      "type": "energy_report",
      "device_id": "dev_fr_01",
      "sim_time": "2026-10-19T09:45:00+02:00",
      "data": { "interval_start": "2026-10-19T09:30:00+02:00", "energy_kwh": 0.03 }
    },
    {
      "event_id": "evt_…",
      "simulation_id": "sim_4f1c…",
      "type": "device_error",
      "device_id": "dev_dw_01",
      "sim_time": "2026-10-19T09:45:00+02:00",
      "data": { "code": "device_unreachable", "message": "Brak odpowiedzi urządzenia: …" }
    }
  ]
}
```

| Pole | Opis |
|---|---|
| `event_id` | `evt_` i losowy UUID: unikalny także między restartami huba. Hub nadaje go przy dodaniu do kolejki, więc ponowiona partia ma te same identyfikatory |
| `simulation_id` | Przebieg symulacji z `GET /home/clock`, w którym zdarzenie zaszło |

| `type` | Kiedy | `data` |
|---|---|---|
| `device_started` | Urządzenie zaczęło pracę / program / przebieg | `program_id` (`null` dla urządzeń bez programów), `command_id` (`null`, gdy start bez polecenia huba), `ref` (akcja przebiegu przy `run_profile`, inaczej `null`) |
| `device_finished` | Koniec programu albo przebiegu, wyłączenie w trakcie | `program_id`, `started_at`, `energy_kwh` cyklu, `interrupted`, `ref` |
| `energy_report` | Po każdym ticku z niezerową energią urządzenia (zwykle co kwadrans) | `interval_start`, `energy_kwh` kroku `[interval_start, sim_time)`, ujemna dla PV |
| `device_error` | Urządzenie nie odpowiada na tick, nie wykonało zaplanowanej komendy albo wyczerpało limit restartów (`code: restart_limit_exceeded`) | `code`, `message` |

Ręczne przełączenie urządzenia w trakcie przebiegu jest w zdarzeniach osobnymi akcjami:
przebieg kończy się `device_finished` z `ref` i `interrupted: true`, a ręczne włączenie zaczyna
`device_started` z `ref: null`.

**Energia.** Zużycie to suma `energy_report`; jest ich tyle, ile ticków z energią, a ich suma dla
urządzenia równa się energii urządzenia (`total_kwh`, suma `energy_kwh` jego cykli `device_finished`).
`energy_kwh` w `device_finished` opisuje cykl i nie wchodzi do sumy drugi raz.

### Dostawa

| Odpowiedź backendu | Hub |
|---|---|
| `202 {"accepted": 3, "duplicates": 1}` | Usuwa partię z kolejki. `accepted` – zapisane teraz, `duplicates` – pominięte, bo już były |
| Timeout, brak połączenia, `5xx`, `408`, `429` | Ponawia tę samą partię z rosnącą przerwą (0,5 s, 1 s, … do 30 s) |
| `401`, `403` | Nie ponawia: loguje błąd konfiguracji `HUB_API_KEY` i odrzuca partię |
| Inne `4xx` (np. `422` za niepoprawne zdarzenie) | Nie ponawia: loguje odpowiedź i odrzuca partię |

- Partie idą po kolei, jedna naraz, do 500 zdarzeń. Backend przyjmuje najwyżej 1000.
- Kolejka jest w pamięci i mieści `HUB_EVENT_BUFFER_SIZE` zdarzeń (domyślnie 50 000, kilkanaście minut
  niedostępności backendu przy dobie w 5 minut). Po przepełnieniu hub odrzuca najstarsze i loguje błąd.
- Przy zamykaniu hub raz próbuje wysłać resztę kolejki (do 5 s); czego nie wyśle, to traci. Restart huba
  i tak zaczyna nowy przebieg symulacji, więc utracone zdarzenia dotyczą tylko zakończonego przebiegu.
- Bez `BACKEND_URL` hub nie zbiera zdarzeń i loguje to przy starcie.

### Backend

- Uwierzytelnienie tym samym `X-Hub-Api-Key` co żądania backendu do huba, bez tokenu użytkownika. Brak
  albo błędny klucz, a także brak `HUB_API_KEY` w backendzie: `401 {"code": "invalid_api_key"}`.
- Zdarzenia trafiają do `home_events` z właścicielem podłączonego domu (`NULL`, gdy dom jest odłączony).
  Unikalny `event_id` i `INSERT … ON CONFLICT DO NOTHING`: ta sama partia wysłana dwa razy, także
  równolegle, niczego nie dubluje.
- Partia z niepoprawnym zdarzeniem (np. `energy_report` bez `energy_kwh`, czas bez strefy,
  `interval_start` nie wcześniejszy niż `sim_time`) jest odrzucana w całości: `422`.
- Nieznany `type` jest zapisywany bez interpretacji, żeby nowszy hub nie tracił całych partii.

## 4. Frontend → backend: dom właściciela

Dom należy do konta z `HUB_HOME_USER_EMAIL` (porównanie bez wielkości liter). Tylko to konto ma
`home_owner: true` w `GET /api/v1/users/me`, widzi ekran „Mój dom” (`/home` w menu) i „Podłącz dom”
na nim oraz na stronie importu. Endpointy domu
wymagają tokenu jak pozostałe; inne konto dostaje `403`, a przy pustym `HUB_URL` wszyscy dostają `503`.

| Metoda i ścieżka | Opis |
|---|---|
| `GET /api/v1/home` | Podłączenie domu i stan wysyłki rejestru |
| `GET /api/v1/home/state` | Zegar, urządzenia, moc, zużycie i koszt doby ([niżej](#get-apiv1homestate--stan-podłączonego-domu)) |
| `POST /api/v1/home/connect` | Podłącza dom i wysyła rejestr. Wysyła go zawsze, także niezmieniony, więc ponowne wywołanie naprawia hub (np. po utracie wolumenu `hub_data`) |
| `DELETE /api/v1/home` | Odłącza dom: hub dostaje pusty rejestr i zatrzymuje mikroserwisy urządzeń |
| `POST /api/v1/home/devices/{device_id}/commands` | Polecenie dla urządzenia ([niżej](#sterowanie-domem)) |
| `PUT /api/v1/home/clock` | Start, pauza, tempo i doba zegara symulacji ([niżej](#sterowanie-domem)) |
| `POST /api/v1/home/plan-runs` | Uruchamia zatwierdzony plan dnia w symulacji ([niżej](#wykonanie-planu-dnia)) |
| `GET /api/v1/home/plan-runs/latest` | Ostatni przebieg planu z raportem albo `null` |
| `POST /api/v1/home/plan-runs/{run_id}/end` | „Zakończ”: kasuje zaplanowane komendy przebiegu, zatrzymuje zegar i zamyka przebieg |
| `GET /api/v1/home/plan-runs` | Historia: do 30 ostatnich przebiegów z rachunkiem z zapisanego raportu |
| `GET /api/v1/home/plan-runs/{run_id}` | Raport jednego przebiegu, jak `…/latest` |

`GET /api/v1/home`, `POST /api/v1/home/connect` i `DELETE /api/v1/home` odpowiadają `200` ze stanem podłączenia:

```json
{
  "connected": true,
  "connected_at": "2026-11-08T20:00:00Z",
  "devices_count": 24,
  "sync": { "status": "pending", "synced_at": "2026-11-08T20:00:00Z", "error": "Hub Smart Home jest niedostępny. Urządzenia zostaną wysłane przy kolejnej operacji." }
}
```

| Pole | Opis |
|---|---|
| `devices_count` | Urządzenia, które hub ma mieć: rejestr właściciela, a po odłączeniu `0` |
| `sync.status` | `synced` – hub przyjął aktualny rejestr; `pending` – rejestr czeka na wysyłkę |
| `sync.synced_at` | Ostatnia udana wysyłka |
| `sync.error` | Powód zaległej wysyłki: hub niedostępny, błędny klucz albo odrzucony rejestr (np. `port_pool_exhausted`) |

### Rejestr i jego wysyłka

- Rejestr to urządzenia domu właściciela z bazy (`device_instances` z programami), czyli scalony
  stan wszystkich jego plików urządzeń, w kształcie `PUT /home/devices`, posortowany po `device_id`
  i `program_id`.
- Backend zapisuje skrót SHA-256 rejestru, który hub ostatnio przyjął (`home_connection`). Import
  i usunięcie pliku przez właściciela wysyłają rejestr tylko wtedy, gdy jego skrót się zmienił,
  więc plik z licznika ani ponowny import tych samych urządzeń nie dotykają huba.
- Wysyłka następuje po zatwierdzeniu importu w bazie. Niedostępny hub nie cofa importu: odpowiedź
  `POST /api/v1/upload` ma `home_sync` ze `status: "pending"` i powodem w `error`, a rejestr wysyła
  kolejna operacja właściciela (import, usunięcie pliku, podłączenie). Ponowienie jest bezpieczne, bo
  rejestr zawsze odpowiada bieżącemu stanowi bazy, a hub nie restartuje niezmienionych urządzeń.
- `home_sync` w odpowiedzi uploadu ma wartość `null`, gdy plik wgrał ktoś inny albo dom jest
  odłączony. Pliki innych użytkowników nigdy nie trafiają do huba.
- Wysyłki są szeregowane blokadą wiersza `home_connection` (`SELECT … FOR UPDATE`), więc starszy
  rejestr nie nadpisze nowszego, także przy kilku workerach backendu.
- Dopóki backend niczego do huba nie wysłał, stan huba jest nieznany i import właściciela przed
  pierwszym podłączeniem nie dotyka huba.
- Zmiana `HUB_HOME_USER_EMAIL` odłącza dom poprzedniego właściciela: pierwsza operacja nowego
  właściciela wysyła pusty rejestr albo, po podłączeniu, jego urządzenia.

### `GET /api/v1/home/state` – stan podłączonego domu

Dla właściciela podłączonego domu; odłączony dom: `409`. Zegar, stany i moc urządzeń backend czyta z huba
(`GET /home/clock`, `GET /home/devices`), a zużycie i koszt doby liczy ze zdarzeń `energy_report` w bazie.

```json
{
  "hub_available": true,
  "simulation_id": "sim_4f1c…",
  "clock": { "sim_time": "2026-10-19T12:00:00+02:00", "running": true, "speed": 288.0 },
  "power": { "consumption_kw": 1.86, "production_kw": 3.0, "net_kw": -1.14 },
  "devices": [
    {
      "device_id": "dev_wm_01",
      "device_name": "Pralka Bosch",
      "device_type": "washing_machine",
      "device_category": "AGD",
      "room": "bathroom",
      "flexibility_mode": "shiftable",
      "programs": [{ "program_id": "cotton_60", "program_name": "Bawełna 60°C", "duration_min": 120 }],
      "state": "running",
      "program_id": "cotton_60",
      "program_started_at": "2026-10-19T11:30:00+02:00",
      "program_ends_at": "2026-10-19T13:30:00+02:00",
      "power_kw": 1.8,
      "energy_today_kwh": 0.9
    }
  ],
  "today": {
    "period": "day",
    "plan_date": null,
    "day_start": "2026-10-19T00:00:00+02:00",
    "until": "2026-10-19T12:00:00+02:00",
    "consumption_kwh": 6.42,
    "production_kwh": 9.0,
    "net_kwh": -2.58,
    "grid_import_kwh": 4.1,
    "cost_pln": 3.7215,
    "cost_error": null
  }
}
```

| Pole | Opis |
|---|---|
| `hub_available` | `false`, gdy hub nie odpowiedział: wtedy `clock` i `power` mają `null`, `devices` jest puste, a `today` dotyczy ostatniego przebiegu ze zdarzeń w bazie (do czasu jego ostatniego zdarzenia) |
| `power` | Suma bieżącej mocy urządzeń: pobór, produkcja PV i bilans (ujemny = oddawanie do sieci) |
| `devices[].device_type`, `device_category`, `room`, `flexibility_mode`, `programs` | Opis urządzenia z rejestru w bazie (programy bez profilu). `room` to pomieszczenie z pliku albo domyślne według typu (słownik w `docs/devices-file-format.md`). `null` i pusta lista, gdy hub ma urządzenie spoza rejestru, np. przy zaległej wysyłce |
| `devices[].energy_today_kwh` | Energia urządzenia od początku doby ze zdarzeń, odporna na restart mikroserwisu |
| `today` | Bilans całego domu od `day_start` do `clock.sim_time`, tylko bieżący przebieg (`simulation_id`). Zwykle od północy doby symulacji (strefa domu, doba ze zmianą czasu ma 23 albo 25 h) |
| `today.period`, `today.plan_date` | `day` – od północy doby. `plan_run` – symulacja jest przebiegiem planu dnia na `plan_date`, a zegar jest w jego horyzoncie: `day_start` to `horizon_start` przebiegu (północ doby planu), także po północy drugiego dnia aż do końca przebiegu. Ten sam okres liczy raport przebiegu, który jednak porównuje tylko urządzenia z planu. Po `horizon_end` wraca `day`. `devices[].energy_today_kwh` liczy się w tym samym okresie |
| `today.grid_import_kwh` | Suma dodatnich bilansów kwadransów: produkcja PV w tym samym kwadransie pokrywa zużycie domu |
| `today.cost_pln` | `grid_import_kwh` kwadransów razy ceny kwadransów taryfy z profilu właściciela (energia, dystrybucja zmienna, opłaty za kWh, VAT; te same ceny co optymalizacja harmonogramu). Bez opłat stałych i bez wartości energii oddanej do sieci, które rozlicza rachunek okresu |
| `today.cost_error` | Powód braku kosztu (`cost_pln: null`), np. niepełny profil albo brak cen RCE dla taryfy dynamicznej |

Zdarzenia dochodzą partią po każdym ticku, więc `today` może nie obejmować jeszcze ostatniego kwadransu.

### Sterowanie domem

Oba endpointy działają tylko dla podłączonego domu (odłączony: `409`) i przekazują polecenie do huba
(`POST /home/devices/{device_id}/commands`, `PUT /home/clock`), który jest jedynym źródłem stanu.

`POST /api/v1/home/devices/{device_id}/commands` przyjmuje treść jak komenda huba (`on`, `off`,
`start_program` z `program_id`, `run_profile` z `profile_kwh` i `ref`, opcjonalnie `start_at`)
i odpowiada `202` z wynikiem huba.

`PUT /api/v1/home/clock` przyjmuje dowolny niepusty podzbiór pól i odpowiada `200` ze stanem zegara
(`sim_time`, `running`, `speed`, `stop_at`):

```json
{ "day": "2026-10-25", "running": false, "speed": 288 }
```

| Pole | Opis |
|---|---|
| `day` | Doba `RRRR-MM-DD`: backend ustawia `sim_time` na północ tej doby w strefie domu, co zaczyna nową symulację (z `restart: true`, więc także dla doby, na której zegar już stoi). Tylko przy zatrzymanym zegarze (inaczej `409` z huba). Backend liczy przesunięcie strefy, bo zależy ono od daty |
| `running` | `true` start, `false` pauza |
| `speed` | Tempo `> 0`, sekundy symulacji na sekundę rzeczywistą |

#### Wykonanie planu dnia

`POST /api/v1/home/plan-runs` z `{ "plan_id": "…" }` uruchamia **zatwierdzony** plan z ekranu „Plan na
jutro” (szkic: `409`, plan sprzed ZP-113 bez profili: `409` z prośbą o ponowne ułożenie). Backend:

1. zatrzymuje zegar, ustawia `sim_time` na północ doby planu z `restart: true`,
2. wysyła **jednym** `POST /home/commands` całą dobę, niezależnie od liczby akcji:
   - pozycje planu ze startem z planu w `start_at`: program jako `start_program` z `program_id`,
     a auto, bojler i pompa ciepła jako `run_profile` z profilem z planu (zera w przerwach ładowania),
     bez `ref`, bo z komendą łączy je `command_id`,
   - urządzenia, które pracują same, jako `run_profile`: produkcję PV (od niej zależy, czy plan się
     opłaca, np. pralka w południe z paneli) oraz pompę ciepła i bojler **odznaczone w planie**, bo plan
     zakłada, że pracują same na termostacie, i liczy na nie miejsce w limicie przyłącza. Od ZP-120 to
     migawka z planu (`background`): PV z prognozy pogody na dobę planu (`ref` = `pv_forecast_RRRR-MM-DD`),
     pompa dopasowana do temperatury, a bojler i to, czego nie dało się policzyć z pogody, z dnia
     referencyjnego, jak niżej. Plan sprzed ZP-120 nie ma migawki: wtedy wszystko z dnia referencyjnego.
     Dzień referencyjny to „wczoraj” jak w planie, liczony dla każdego urządzenia osobno: dzień startu
     jego ostatniej akcji przed dobą planu, a bez takiej (plan sprzed całej historii) ostatniej w ogóle.
     Doba tego dnia (00:00–24:00, bez nocy po niej) trafia na te same godziny doby planu. `profile_kwh` to kwadranse akcji z `device_slot_usage`
     (ten sam rozkład co wycena i wykresy, ujemny dla PV), a `ref` to `action_id` z pliku. Kwadranse
     przykryte nowszym plikiem (`superseded`) są pomijane, przerwa w kwadransach akcji dzieli ją na osobne
     przebiegi, a nachodzące na siebie przebiegi jednego urządzenia są łączone w jeden.

   Urządzenia stałe (światło, TV, czajnik, piekarnik…) startują wyłączone i reagują tylko na ręczne
   włączenie z ekranu „Mój dom”: widać wtedy, jak plan i ręczne włączenia razem obciążają przyłącze.
3. zapisuje przebieg (`plan_runs`) z migawką pozycji planu i wynikiem ich komend,
4. uruchamia zegar z bieżącym tempem i `stop_at` na koniec przebiegu, więc hub sam staje. Koniec przebiegu
   (`horizon_end`) to północ po dobie planu albo koniec ostatniej wysłanej pozycji planu, jeśli pracuje dłużej
   (np. nocne ładowanie auta), najpóźniej 06:00 jak zakres planu. Po północy bez pracy z planu nie ma czego
   symulować.

Gdy któryś krok zawiedzie, przebieg nie jest zapisywany, a ponowienie zaczyna dobę od nowa. Odrzucona
komenda (np. `device_not_found`) nie blokuje pozostałych: przebieg rusza, a raport podaje jej powód.

Odpowiedź (`201`, a w `GET …/latest` i `POST …/end` `200`):

```json
{
  "id": "…", "plan_id": "…", "plan_date": "2026-10-12", "status": "running", "simulation_id": "sim_4f1c…",
  "started_at": "2026-11-15T10:00:00Z", "ended_at": null, "sim_time": "2026-10-12T13:15:00+02:00",
  "horizon_start": "2026-10-12T00:00:00+02:00", "horizon_end": "2026-10-13T06:00:00+02:00",
  "history_day": "2026-10-05",
  "replay": { "actions": 2, "devices": 2, "skipped_devices": [], "rejected_actions": 0 },
  "replayed_devices": [
    { "device_id": "dev_pv_01", "device_name": "Instalacja PV", "history_day": "2026-10-05",
      "history_kwh": -12.6, "actual_kwh": -7.9, "source": "forecast", "reference_kwh": -18.2 },
    { "device_id": "dev_hp_01", "device_name": "Pompa ciepła", "history_day": "2026-10-05",
      "history_kwh": 9.5, "actual_kwh": 4.1, "source": "history", "reference_kwh": 9.5 }
  ],
  "planned_kwh": 6.4, "actual_kwh": 0.6,
  "devices": [{
    "device_id": "dev_wm_01", "device_name": "Pralka Bosch", "kind": "program", "planned_kwh": 1.4, "actual_kwh": 0.6,
    "actions": [{ "action_id": "dev_wm_01", "label": "Bawełna 60°C", "start": "2026-10-12T13:00:00+02:00",
                  "end": "2026-10-12T15:00:00+02:00", "energy_kwh": 1.4, "status": "scheduled", "code": null, "detail": null }]
  }],
  "errors": [{ "device_id": "dev_lamp_01", "device_name": "Lampa", "sim_time": "2026-10-12T18:15:00+02:00",
               "code": "invalid_state", "message": "Trwa przebieg urządzenia" }]
}
```

| Pole | Opis |
|---|---|
| `status` | `running`; `completed`, gdy zegar przebiegu minie `horizon_end`; `ended` po „Zakończ”; `superseded`, gdy hub zaczął inną symulację (kolejny przebieg, ustawienie doby, restart huba). Backend sprawdza to w hubie przy odczycie; bez huba zostaje ostatni znany status |
| `sim_time` | Bieżący czas przebiegu, a po jego końcu chwila, w której się skończył |
| `devices` | Urządzenia z planu: energia według planu i zużyta w symulacji (zdarzenia `energy_report` przebiegu od początku planu do `sim_time`) |
| `history_day` | Najnowszy z dni referencyjnych w `replayed_devices` (zwykle wszystkie urządzenia mają ten sam); `null`, gdy nie było czego odtwarzać |
| `replay` | Przebiegi z historii: `actions` i `devices` przyjęte przez hub, `skipped_devices` spoza rejestru huba (`device_not_found`, np. przy zaległej wysyłce rejestru), `rejected_actions` odrzucone z innego powodu (np. `409 invalid_state`) |
| `replayed_devices` | Urządzenia pracujące same, których przebiegi hub przyjął: dzień referencyjny (`history_day`, `null` dla PV z prognozy bez historii), energia wysłana do huba (`history_kwh`), zużyta w symulacji (`actual_kwh`) i energia dnia referencyjnego (`reference_kwh`), ujemne dla PV. `source`: `forecast` (PV z prognozy pogody, pompa dopasowana do temperatury) albo `history` (doba dnia referencyjnego). Nie wchodzą do `planned_kwh` i `actual_kwh` przebiegu, które dotyczą tylko urządzeń planu |
| `errors` | Do 50 ostatnich `device_error` przebiegu, np. komenda, której urządzenie nie wykonało o `start_at` |
| `prices` | Ceny kwadransów planu (`start`, `price_pln_kwh`) z migawki przy starcie przebiegu: pasek czasu i cena teraz na ekranie „Mój dom” (ZP-110). Puste w przebiegach sprzed tej zmiany |
| `water_heaters` | Bojlery z planu: `device_id`, `device_name` i temperatura wody według planu na końcu każdego kwadransu (`temperatures[]`: `start`, `temp_c`). Zaplanowana, nie zmierzona: hub nie liczy temperatury |

„Zakończ” najpierw kasuje kolejkę huba (`DELETE /home/commands`): wszystkie zaplanowane komendy
przebiegu, czyli resztę planu i historii (np. PV od 10:00, kolejne bloki pompy ciepła). Potem zatrzymuje
zegar, kasuje `stop_at` i oznacza przebieg jako `ended`. Ręczny Start później nie stanie nagle o 06:00
ani nie uruchomi np. ładowania auta z zakończonego planu. To, co urządzenia już wykonują (pralka
w połowie programu, PV w trakcie produkcji), po Starcie się dokończy; wyłączyć można je ręcznie. Gdy hub
zawiedzie po drodze, przebieg zostaje `running` z zatrzymaniem o końcu planu, a ponowne „Zakończ” robi
wszystko jeszcze raz. Zakończony przebieg zostaje bez zmian.
Do chwilowej przerwy służy pauza zegara, a ponowne uruchomienie zaczyna plan od północy.

#### Rachunek przed i po

Pole `cost` przebiegu (ZP-114; `null` w przebiegach sprzed niego) porównuje urządzenia z planu bez planu
i z planem. Drugiej symulacji „bez planu” nie ma: plan ma dla każdej akcji start bazowy (zwykła godzina
z historii, ładowanie od podłączenia, termostat bojlera, bloki pompy z historii), a backend przy
uruchomieniu wycenia go cenami kwadransów planu i zapisuje razem z cenami w przebiegu (ponowne ułożenie
planu nadpisuje jego wiersz). Z planem to energia zmierzona w symulacji (`energy_report`) razy te same
ceny. Bez odchyleń oszczędność jest równa oszczędności planu.

```json
"cost": {
  "complete": true, "until": "2026-10-13T06:00:00+02:00",
  "cost_before": 6.4, "cost_after": 1.78, "planned_cost": 1.78, "saving": 4.62, "saving_percent": 72.2,
  "devices": [{ "device_id": "dev_wm_01", "device_name": "Pralka Bosch", "kind": "program",
                "energy_before_kwh": 1.4, "energy_after_kwh": 1.4, "cost_before": 1.2, "planned_cost": 0.4,
                "cost_after": 0.4, "saving": 0.8 }],
  "excluded": [], "pending": [],
  "manual": [{ "device_id": "dev_lamp_01", "device_name": "Lampa", "energy_kwh": 0.2, "cost": 0.12 }],
  "manual_cost": 0.12,
  "pv": { "production_kwh": 6.4, "self_consumption_kwh": 3.1, "plan_from_pv_kwh": 0.9, "plan_kwh": 6.4 },
  "deviations": [{ "kind": "grid_limit", "device_id": null, "device_name": null,
                   "sim_time": "2026-10-12T19:00:00+02:00", "end": "2026-10-12T19:30:00+02:00",
                   "message": "Pobór z sieci do 4,40 kW, a limit przyłącza to 3,00 kW.", "excluded": false }]
}
```

- Porównanie jest per urządzenie. Urządzenie wypada z niego (`excluded`), gdy hub odrzucił jego komendę,
  zgłosiło awarię, zostało ręcznie wyłączone w trakcie pracy (`device_finished` z `interrupted: true`)
  albo ręcznie włączone poza planem (`device_started` z `command_id` spoza komend przebiegu).
- Inne zużycie niż w planie (ponad 1%) i pobór z sieci ponad `max_grid_kw` planu (plan razem z ręcznymi
  włączeniami, sąsiednie kwadranse razem) są w `deviations`, ale nie wykluczają.
- Urządzenia stałe włączane ręcznie (`manual`) i PV (`pv`) są poza oszczędnością. Koszty to energia razy cena
  kwadransu, bez bilansowania z PV, tak jak w planie; `pv` podaje autokonsumpcję w kwadransie i jej część
  przypadającą na urządzenia z planu (w proporcji do ich zużycia).
- Przed końcem planu (`running`, `ended`, `superseded`) raport jest niepełny (`complete: false`):
  porównuje urządzenia, których akcje skończyły się do `until`, a resztę podaje w `pending`.
- Raport zapisuje się przy zamknięciu przebiegu i przez 5 minut jeszcze się przelicza, bo hub dosyła
  zdarzenia z kolejki z opóźnieniem. Potem `GET` zwraca zapisany raport, a historia przebiegów
  (`GET …/plan-runs`) podaje z niego `complete`, koszty, oszczędność i liczbę odchyleń.

Błędy huba:

| Sytuacja | Odpowiedź |
|---|---|
| Hub odrzucił polecenie z kodem kontraktu (np. `409 invalid_state`, `404 program_not_found`) | Ten sam status, opis huba w `detail` |
| Brak połączenia z hubem albo `5xx` huba | `503`, można ponowić |
| Hub nie odpowiedział na komendę w czasie (mógł ją wykonać) | `504`: przed ponowieniem trzeba sprawdzić stan urządzenia |
| Urządzenie bez odpowiedzi, nieudany reset urządzeń przy zmianie doby | `502` z opisem |
| Błędny `HUB_API_KEY` albo odpowiedź spoza kontraktu (np. `4xx` bez `code`) | `502` z opisem |

#### Statystyki na żywo (ZP-153)

Pole `live` przebiegu (`GET …/plan-runs/latest`) liczy backend przy każdym odczycie z migawki przebiegu
i zdarzeń energii do bieżącego czasu symulacji (`until`), bez pytania huba i pogody (`plan_run_live.py`).
Ekran odświeża przebieg razem ze stanem domu, więc wartości idą z zegarem, a pauza je zatrzymuje.

```json
"live": {
  "until": "2026-10-12T14:10:00+02:00",
  "indoor": [{ "device_id": "dev_hp_01", "device_name": "Pompa ciepła", "at": "2026-10-12T14:00:00+02:00",
               "temp_c": 21.3, "plan_c": 21.3, "set_c": 21, "band": [20, 22],
               "points": [{ "start": "2026-10-12T00:00:00+02:00", "plan_c": 20.9, "temp_c": 20.9 }] }],
  "weather": { "start": "2026-10-12T14:00:00+02:00", "temperature_c": 6.4, "cloud_cover_pct": 80, "past": false },
  "pv": { "production_kwh": 4.2, "self_kwh": 3.1, "export_kwh": 1.1, "export_pln": 0.55, "planned_kwh": 6.5,
          "hours": [{ "start": "2026-10-12T13:00:00+02:00", "planned_kwh": 1.2, "actual_kwh": 1.1 }] },
  "price_now": 0.88, "export_price_now": 0.45,
  "saving": { "cost_before": 5.2, "cost_after": 3.9, "saving": 1.3, "saving_percent": 25.0, "excluded": [],
              "planned_saving": 2.1 }
}
```

- `indoor` (dom z pompą w planie trzymającym temperaturę): migawka przy starcie ma model domu z planera
  (straty, pojemność, ogrzewanie podłogowe, ustawiona temperatura) i temperaturę na dworze co kwadrans.
  Temperaturę liczymy `House.step` na energii pompy zmierzonej w symulacji, bez grzania wody z planu
  (`#woda`), do końca ostatniego pełnego kwadransu (`at`). Przy pracy według planu zgadza się z wykresem
  planu (`plan_c`), a po ręcznym wyłączeniu pompy spada. `points`: cała doba według planu i z symulacji do
  teraz (`temp_c = null` po `until`), do wykresu w kafelku.
- `weather`: kwadrans zegara z pogody zapisanej w planie (prognoza, a w planie idealnym archiwum).
- `pv`: produkcja od początku planu w bilansie godzinowym jak `pv_balance.summary`: w każdej godzinie dom
  zużywa min(produkcja, zużycie wszystkich urządzeń, także ręcznych), a reszta idzie do sieci, więc
  `self_kwh + export_kwh = production_kwh`; produkcja to ta sama co w bilansie `home/state`. Wartość
  oddania z cen oddania w migawce planu. Bez PV w domu `null`. `planned_kwh` i `hours`: produkcja, na którą
  liczy plan, obok zmierzonej godzina po godzinie (bieżąca godzina: tyle, ile już zmierzono). W symulacji
  urządzenia stałe są wyłączone, dopóki ich nie włączysz, więc dom zużywa mniej niż w planie i oddaje więcej.
- `price_now`: cena z sieci w kwadransie zegara; `export_price_now`: wartość kWh oddanej w tej godzinie
  (tylko plan z PV).
- `saving`: urządzenia z planu od początku planu do `until`. Bez planu to profil bazowy z migawki
  (`original_profile_kwh`) przycięty do `until`, a kwadrans z `until` w części, która minęła. Z planem to
  energia zmierzona. Wycena jak w raporcie: ceny kwadransów, a w planie z PV rachunek domu w godzinach
  (`HouseBalance.allocate`). Urządzenia w trakcie pracy też się liczą (w raporcie są w `pending`), a urządzenia
  z odchyleniem wykluczającym (`excluded`) wypadają tak jak w raporcie. Po końcu planu bez planu to cały
  profil, więc wynik to raport. Przebiegi sprzed ZP-153 nie mają profili: `saving = null`.
  `planned_saving` to oszczędność planu w całej dobie (bez urządzeń z odchyleniem): plan przesuwa pracę w czasie,
  więc „do teraz” bywa w trakcie doby większe albo mniejsze (np. o 02:00 pompa bez planu już grzała, a plan
  zaczyna później).

**Pompa ciepła w hubie.** Plan ma osobno grzanie domu (`#dom`, cała doba) i ciepłą wodę (`#woda`), a urządzenie
wykonuje naraz jeden profil: hub odrzuciłby wodę („Trwa przebieg urządzenia”). Pozycje jednego urządzenia, których
profile nachodzą na siebie, idą więc jako jedna komenda `run_profile` z sumą profili (`_plan_commands`); w kwadransach
wody plan nie grzeje domu, więc suma jest dokładna, a obie pozycje mają ten sam wynik komendy.

Panel „Na żywo” jest nad przekrojem domu w zakładce „Symulacja” (na telefonie zwinięty). Bez trwającego
przebiegu pokazuje pogodę doby symulacji i produkcję PV z bilansu doby z podpowiedzią, żeby uruchomić plan.

Ekran „Mój dom” odpytuje `GET /api/v1/home/state` co 2 s przy działającym zegarze i co 10 s przy
pauzie, a po każdym poleceniu od razu. Kolejne żądanie wychodzi po odpowiedzi poprzedniego, a ukryta
karta przeglądarki nie odpytuje backendu.

## Konfiguracja

| Zmienna | Strona | Opis |
|---|---|---|
| `HUB_URL` | backend | Adres huba, w docker-compose `http://hub:9100`; pusty = Smart Home wyłączony |
| `HUB_API_KEY` | backend, hub | Wspólny klucz `X-Hub-Api-Key` |
| `HUB_TIMEOUT_SECONDS` | backend | Timeout żądań do huba, domyślnie 5 s |
| `HUB_HOME_USER_EMAIL` | backend | E-mail konta, do którego należy dom huba; pusty = nikt nie może podłączyć domu |
| `BACKEND_URL` | hub | Adres backendu dla webhooka, w docker-compose `http://backend:8000`; pusty = zdarzenia nie są wysyłane |
| `HUB_EVENT_BUFFER_SIZE` | hub | Ile zdarzeń czeka najwyżej na wysyłkę do backendu, domyślnie 50 000 |
| `DEVICE_BIND_HOST` | hub | Adres nasłuchu urządzeń: `127.0.0.1` domyślnie, `0.0.0.0` w trybie demo |
| `HUB_STATE_DIR` | hub | Katalog pliku stanu i konfiguracji urządzeń, domyślnie `/data` |
| `HUB_HEALTH_INTERVAL_SECONDS` | hub | Co ile sekund hub sprawdza urządzenia, domyślnie 5 |

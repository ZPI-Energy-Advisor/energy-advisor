# Format pliku urządzeń (JSON)

Plik urządzeń opisuje wszystkie urządzenia w domu i to, kiedy i ile energii zużyły. Odpowiada
danym, do których ma dostęp centrum smart home (np. HomeKit): lista urządzeń z parametrami oraz
historia ich pracy. Na jego podstawie aplikacja:

- liczy zużycie w podziale na kategorie urządzeń i wycenia je w taryfach,
- optymalizuje pracę urządzeń, które da się przesunąć w czasie,
- odtwarza dom w symulacji Smart Home (hub i urządzenia na portach localhosta).

Przykładowy plik: [`frontend/public/samples/devices-example.json`](../frontend/public/samples/devices-example.json)
(24 urządzenia, 2 doby, link do pobrania na ekranie importu).

Strukturę pliku (pola, typy, słowniki, formaty) opisuje formalnie JSON Schema
[`backend/app/parsers/devices_file.schema.json`](../backend/app/parsers/devices_file.schema.json).
Reguły z tego dokumentu sprawdza `backend/app/parsers/device_validation.py` w dwóch krokach: najpierw
schemat, potem reguły łączące pola i obiekty, których schemat nie wyrazi. Korzysta z tego import
pliku w aplikacji i skrypt wiersza poleceń:

```bash
python backend/scripts/validate_devices_file.py frontend/public/samples/devices-example.json
python backend/scripts/validate_devices_file.py plik.json --max-grid-kw 12
```

## Generator danych

Dłuższe, realistyczne dane w tym formacie tworzy `backend/scripts/generate_devices_file.py`.
Symuluje domowników (dni robocze, praca zdalna, weekendy), pracę urządzeń według pór dnia,
zmierzchu i pory roku oraz produkcję PV w dni słoneczne i pochmurne. Ten sam seed i te same
parametry dają identyczny plik, a wynik zawsze przechodzi walidację.

```bash
python backend/scripts/generate_devices_file.py --out devices.json
python backend/scripts/generate_devices_file.py --start 2026-10-01 --days 30 --seed 42 \
    --devices full --with-pv --out backend/tests/fixtures/devices_demo_30d.json
```

| Parametr | Domyślnie | Znaczenie |
|---|---|---|
| `--start` | `2026-10-01` | pierwsza doba |
| `--days` | `30` | liczba dób |
| `--seed` | `42` | ziarno losowania |
| `--devices` | `full` | `standard`: bez EV, pompy ciepła i rekuperatora; `full`: wszystkie urządzenia |
| `--with-pv` | wyłączone | dodaje instalację PV |
| `--max-grid-kw` | `9` | limit przyłącza; generator przesuwa akcje, żeby go nie przekroczyć |
| `--out` | wymagany | plik wynikowy |

Plik demo `backend/tests/fixtures/devices_demo_30d.json` (30 dób od 1.10.2026, z PV) służy
jako fixtures do testów i dane do prezentacji. Obejmuje zmianę czasu 25.10.2026 (doba ze 100
kwadransami). Test pilnuje, że plik odpowiada generatorowi, więc po zmianie generatora trzeba go
wygenerować ponownie powyższym poleceniem.

## Model danych: zdarzenia, nie szereg czasowy

Plik zapisuje **akcje** (np. „pranie Bawełna 60°C od 9:30 do 11:30, 1,95 kWh”), a nie odczyty
licznika co 15 minut. Akcja jest naturalną jednostką, którą optymalizacja przesuwa w czasie,
a symulacja uruchamia na urządzeniu. Aplikacja rozkłada akcje na kwadranse przy imporcie.

Plik zawiera **wszystkie** urządzenia w domu, także te, których optymalizacja nie rusza
(oświetlenie, lodówka, telewizor). Nie ma osobnego „zużycia bazowego”: każda kWh ma swoje
urządzenie. Wycena pliku obejmuje wyłącznie wymienione urządzenia.

## Struktura

```json
{
  "period": { "start": "...", "end": "..." },
  "devices": [ ... ],
  "energy_usage": [ ... ]
}
```

Nieznane pola są ignorowane, dzięki czemu format można rozszerzać bez psucia starszych plików.

## Czas i ziarnistość

- Wszystkie znaczniki czasu w formacie ISO 8601 **z przesunięciem strefy**, np.
  `2026-10-19T09:30:00+02:00`. Znacznik bez strefy jest błędem.
- Ziarnistość to **15 minut**, tak jak ceny RCE. Starty i końce akcji wypadają na pełnych
  kwadransach (`:00`, `:15`, `:30`, `:45`), a profile energii mają jedną wartość na kwadrans.
- Podział na doby odbywa się w strefie `Europe/Warsaw`. W dniu zmiany czasu doba ma 92 albo
  100 kwadransów, dlatego wewnętrznie aplikacja liczy w UTC.
- Godziny w oknach czasowych (`allowed_window`) mają format `HH:MM` czasu lokalnego.

## `period`

Zakres danych w pliku: `start` włącznie, `end` wyłącznie. Każda akcja musi się w nim mieścić.

Okres jest potrzebny, bo w modelu zdarzeniowym brak akcji jest dwuznaczny. Doba bez żadnej
akcji w środku okresu oznacza „nic nie pracowało”, a nie brak danych.

## `devices`

| Pole | Typ | Wymagane | Opis |
|---|---|---|---|
| `device_id` | string | tak | Unikalny identyfikator w pliku, np. `dev_wm_01` |
| `device_name` | string | tak | Nazwa widoczna w UI, np. „Pralka Bosch” |
| `device_type` | string | tak | Typ ze słownika poniżej |
| `device_category` | string | tak | Kategoria ze słownika poniżej |
| `max_power_kw` | liczba, kW | gdy brak `programs` | Moc maksymalna (znamionowa). Dla PV: moc falownika |
| `flexibility` | obiekt | tak | Co optymalizacja może zrobić z akcjami urządzenia |
| `programs` | lista | nie | Powtarzalne cykle pracy (pralka, zmywarka, suszarka) |

### Kategorie (`device_category`)

`AGD`, `Ogrzewanie`, `OZE`, `Oświetlenie`, `RTV/IT`, `Pojazd elektryczny`, `Inne`.

Tylko urządzenia z kategorii `OZE` mogą mieć ujemną energię (produkcja).

### Typy (`device_type`)

| Typ | Etykieta w UI | Typ | Etykieta w UI |
|---|---|---|---|
| `washing_machine` | Pralka | `heat_pump` | Pompa ciepła |
| `tumble_dryer` | Suszarka do ubrań | `electric_heater` | Grzejnik elektryczny |
| `dishwasher` | Zmywarka | `water_heater` | Podgrzewacz wody |
| `fridge` | Lodówka | `ventilation` | Rekuperator / wentylacja |
| `freezer` | Zamrażarka | `pv_inverter` | Instalacja PV |
| `induction_hob` | Płyta indukcyjna | `light` | Oświetlenie |
| `oven` | Piekarnik | `tv` | Telewizor |
| `microwave` | Kuchenka mikrofalowa | `computer` | Komputer |
| `kettle` | Czajnik | `router` | Router |
| `coffee_machine` | Ekspres do kawy | `ev_charger` | Ładowarka EV |
| `vacuum_cleaner` | Odkurzacz | `hair_dryer` | Suszarka do włosów |
| `other` | Inne urządzenie | | |

### `flexibility`

| `mode` | Znaczenie | Dozwolone pola | Przykłady |
|---|---|---|---|
| `fixed` | O czasie pracy decyduje słońce albo domownik. Optymalizacja nie rusza akcji, symulacja odtwarza je z historii | tylko `mode` | PV, oświetlenie, lodówka, TV, czajnik |
| `shiftable` | Akcję można przesunąć w całości (ten sam profil, inna godzina startu), ale nie przerwać | `allowed_window`, `max_shift_min` | pralka, zmywarka, suszarka, pompa ciepła |
| `interruptible` | Energię można rozłożyć dowolnie na kwadranse w oknie sesji: przerwać, wznowić | `allowed_window` | ładowarka EV |

- `allowed_window` (`{"from": "07:00", "to": "22:00"}`): pora dnia, w której urządzenie może
  pracować. Okno może przechodzić przez północ (`19:00` → `07:00`). Przy przesuwaniu cała akcja
  musi zmieścić się w oknie, a nie tylko jej start.
- `max_shift_min`: maksymalne przesunięcie startu względem historycznego, w obie strony.
- Oba ograniczenia dotyczą optymalizacji. **Akcje historyczne nie są z nimi sprawdzane**:
  użytkownik mógł włączyć pralkę o 23:00 i taki plik jest poprawny.
- Dla `interruptible` okno optymalizacji wyznacza sesja (patrz „Sesje ładowania EV”).
  `allowed_window` ładowarki służy tylko symulacji przyszłych dni, dla których nie ma sesji.

Zalecane ustawienia: pralka, zmywarka i suszarka `shiftable` z oknem dziennym; pompa ciepła
`shiftable` z `max_shift_min: 60`; ładowarka EV `interruptible`; pozostałe `fixed`.

### `programs`

| Pole | Typ | Opis |
|---|---|---|
| `program_id` | string | Unikalny w obrębie urządzenia, np. `cotton_60` |
| `program_name` | string | Nazwa w UI, np. „Bawełna 60°C” |
| `duration_min` | liczba, min | Czas trwania, wielokrotność 15 |
| `profile_kwh` | lista liczb, kWh | Energia w kolejnych kwadransach cyklu, `duration_min / 15` wartości |

Profil programu opisuje kształt cyklu niezależnie od godziny startu (np. grzałka pralki na
początku prania). Optymalizacja przesuwa akcję razem z tym kształtem.

## `energy_usage`

| Pole | Typ | Wymagane | Opis |
|---|---|---|---|
| `action_id` | string | tak | Unikalny identyfikator w pliku |
| `device_id` | string | tak | Urządzenie z listy `devices` |
| `program_id` | string | gdy urządzenie ma `programs` | Program urządzenia; dla urządzeń bez programów pole jest niedozwolone |
| `action_start` | czas | tak | Początek pracy |
| `action_end` | czas | tak | Koniec pracy, później niż `action_start` |
| `energy_kwh` | liczba, kWh | tak | Energia akcji; ujemna tylko dla `OZE` |
| `profile_kwh` | lista liczb, kWh | nie | Własny profil akcji, jedna wartość na kwadrans (np. produkcja PV) |
| `plugged_in` | czas | nie, tylko EV | Moment podłączenia auta; domyślnie `action_start` |
| `deadline` | czas | tak dla EV | Do kiedy auto musi być naładowane |

### Rozkład energii na kwadranse

Energia akcji trafia na kwadranse według pierwszego dostępnego źródła:

1. `profile_kwh` akcji, jeśli jest (np. PV, dane pomiarowe),
2. `profile_kwh` programu wskazanego przez `program_id`,
3. stała moc: `energy_kwh` podzielone równo na kwadranse akcji.

Gdy używany jest profil, jego suma musi być równa `energy_kwh` (tolerancja 0,005 kWh), a liczba
wartości równa liczbie kwadransów akcji.

### Sesje ładowania EV

| Pole | Znaczenie | Do czego służy |
|---|---|---|
| `plugged_in` | podłączenie auta, początek okna | optymalizacja |
| `action_start` – `action_end` | kiedy faktycznie płynął prąd | wycena historii |
| `deadline` | do kiedy auto ma być naładowane, koniec okna | optymalizacja |

Optymalizacja rozkłada `energy_kwh` sesji na najtańsze kwadranse między `plugged_in` a
`deadline`. `deadline` może wypadać po końcu `period`; optymalizacja historyczna traktuje wtedy
koniec okresu jako granicę.

### Produkcja PV

Produkcja jest zapisywana jako akcje z ujemną energią i własnym profilem 15-minutowym, np. od
wschodu do zachodu słońca. Moc instalacji (kWp) i sposób rozliczenia (net-billing,
net-metering) pochodzą z profilu użytkownika, nie z pliku.

## Reguły walidacji

Plik jest poprawny, gdy spełnia wszystkie reguły. Reguły 3–5, typy i wymagane pola, format czasu
ze strefą oraz godzin `allowed_window` sprawdza schemat; pozostałe sprawdza kod. Przy błędach
schematu reguły z kodu nie są sprawdzane, bo wynikałyby z tych samych błędów.

1. `period.start` i `period.end` mają strefę czasową, `start` < `end`.
2. `device_id` i `action_id` są unikalne.
3. `device_type` i `device_category` pochodzą ze słowników.
4. `flexibility.mode` jest jednym z trybów i zawiera tylko pola dozwolone dla tego trybu;
   godziny `allowed_window` mają format `HH:MM` w pełnym kwadransie.
5. Urządzenie bez `programs` ma `max_power_kw`; urządzenie `fixed` nie ma `programs`.
6. Długość profilu programu odpowiada `duration_min`.
7. Każda akcja wskazuje istniejące urządzenie, a `program_id` istnieje wtedy i tylko wtedy,
   gdy urządzenie ma programy, i wskazuje jego program.
8. Każda akcja mieści się w `period`, ma strefę czasową, start przed końcem, a oba wypadają na
   pełnym kwadransie.
9. Suma i długość użytego profilu zgadzają się z `energy_kwh` i czasem trwania akcji.
10. Energia w żadnym kwadransie nie przekracza `max_power_kw` × 0,25 h.
11. Ujemna energia występuje tylko w kategorii `OZE`, a `OZE` ma tylko ujemną energię.
12. Akcje jednego urządzenia nie nakładają się w czasie.
13. Sesja EV ma `deadline` i spełnia `plugged_in ≤ action_start < action_end ≤ deadline`;
    `plugged_in` i `deadline` nie występują przy innych urządzeniach.
14. Łączny pobór domu w żadnym kwadransie nie przekracza limitu przyłącza (w walidatorze
    parametr `--max-grid-kw`). Import w aplikacji na razie tej reguły nie sprawdza, bo profil
    użytkownika nie ma jeszcze mocy przyłączeniowej.


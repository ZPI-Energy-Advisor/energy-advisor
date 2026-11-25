# Prognoza produkcji PV (ZP-118)

Produkcja instalacji PV na każdy kwadrans doby, z pogody (ZP-117) i paneli z profilu (ZP-148), skalibrowana
na produkcji falownika z wgranych plików urządzeń. Kod: `backend/app/services/pv_forecast.py`.

## Model

Dla każdej grupy paneli z profilu (`pv_config.installation.arrays`):

```
moc DC grupy = kWp × G / 1000 × (1 − 0,004 × (T_ogniwa − 25))
T_ogniwa     = T_powietrza + 0,03 × G
```

`G` to promieniowanie na płaszczyznę grupy (`global_tilted_irradiance`, W/m²), `T` temperatura z pogody.
Moc kwadransu to suma grup × współczynnik sprawności, ucięta do mocy falownika, × 0,25 h.

- Współczynnik sprawności (straty instalacji, falownika, zabrudzenie) dopasowujemy do historii domu,
  a bez niej przyjmujemy 0,8.
- Moc falownika bierzemy z profilu (`inverter_power_kw`), a gdy jej tam nie ma, z `max_power_kw` urządzenia
  `pv_inverter` z pliku. Moc falownika tylko ogranicza produkcję, a nie zastępuje kWp.
- Wynik `kwh` jest dodatni. W pliku urządzeń produkcja jest ujemna.

## Kalibracja

Kalibracja bierze produkcję urządzeń `pv_inverter` z plików urządzeń, z pominięciem wersji przykrytych
nowszym plikiem. Do tego bierze pogodę z bazy dla tych samych dni, bez pobierania z internetu.
Historię pobiera worker po imporcie (ZP-117).

1. Dla każdego minionego dnia z produkcją i pełną pogodą liczymy sumę produkcji i sumę modelu bez
   współczynnika. Kwadranse na limicie falownika pomijamy w obu sumach, bo obcięcie zaniża stosunek.
2. Odrzucamy dni, których stosunek odbiega od mediany o więcej niż połowę, np. śnieg na panelach albo
   awaria falownika.
3. Współczynnik to suma produkcji / suma modelu z pozostałych dni. Potrzeba co najmniej 3 dni, inaczej
   zostaje 0,8 z dopiskiem.
4. Współczynnik poza zakresem 0,4–1,1 oznacza, że plik nie pasuje do paneli z profilu, np. inna moc albo
   kierunek. Ucinamy go do zakresu i dopisujemy to w `notes`.
5. Błąd (MAPE dobowy) liczymy metodą „bez jednego dnia”: dzień oceniamy współczynnikiem policzonym
   bez niego.

Kalibracja jest zapamiętywana w procesie. Liczy się ją od nowa po zmianie plików, paneli, lokalizacji
albo falownika i co godzinę (wtedy dochodzi pogoda pobrana w tle). Pierwsza prognoza dla roku danych trwa ok. 0,5 s, kolejne ok. 10 ms.
Kalibracja domyślna, np. gdy historia pogody dopiero się pobiera, nie jest zapamiętywana.

Plik z licznika nie kalibruje prognozy. Ma tylko oddanie do sieci, bez energii zużytej na miejscu, więc
zaniżałby współczynnik. Dom bez pliku urządzeń z PV ma współczynnik 0,8 i dopisek o mniejszej dokładności.

### Jakość na danych demo

Plik demo to `devices_demo_30d.json`: Wrocław, październik 2026, 6 kWp na południe, 35°. Produkcja jest
wygenerowana z prawdziwej pogody modelem bogatszym niż prognoza (zob. [devices-file-format.md](devices-file-format.md)).
Wyniki kalibracji:

| Wynik | Wartość |
|---|---|
| Współczynnik | 0,83 (w generatorze straty 0,83 i losowy współczynnik dnia) |
| MAPE dobowy, „bez jednego dnia” | ok. 4% |
| Największy błąd dnia | ok. 11% (wymaganie: poniżej 25%) |

To błąd modelu przy znanej pogodzie (archiwum). Prognoza na jutro ma do tego błąd prognozy pogody, który
przy zmiennym zachmurzeniu bywa większy od błędu modelu. Śniegu na panelach prognoza nie przewiduje.

Generator dla całego 2025 roku we Wrocławiu daje ok. 1150 kWh z kWp przy współczynniku wydajności 0,79.
Mieści się to w realnych wartościach dla Polski (950–1150 kWh/kWp, wyżej w słoneczne lata).

## Gdy brakuje pogody

| Sytuacja | Co robimy |
|---|---|
| Prognoza w bazie jest starsza niż 3 h, a Open-Meteo nie odpowiada | Bierzemy prognozę z bazy (`weather_fetched_at` mówi, z kiedy) |
| Na dany dzień nie ma pogody albo brakuje części kwadransów | Brakujące kwadranse to średnia z tej samej godziny zegarowej z 7 poprzednich dni w bazie; `basis` = `recent_days` albo `mixed` i dopisek w `notes` |
| Nie ma pogody ani na ten dzień, ani na 7 dni wcześniej | `503`; plan na jutro (ZP-121) traktuje to jak brak prognozy PV, czyli liczy bez nadwyżki |
| Profil bez PV | `404` |
| Panele szacunkowe („Nie znam parametrów”) albo lokalizacja przybliżona | Prognoza jest liczona, z dopiskiem w `notes` |

Średnia z ostatnich dni jest lepsza od kopii wczorajszego dnia: jeden pochmurny albo słoneczny dzień nie
przenosi się wtedy w całości na dzień prognozy.

## API

`GET /api/v1/pv/forecast?date=RRRR-MM-DD` (domyślnie jutro, od 2000-01-01 do dziś + 2 dni):

```json
{
  "date": "2026-11-25", "total_kwh": 3.11, "complete": true, "basis": "weather",
  "calibration": {"coefficient": 0.83, "source": "history", "days": 30, "mape": 0.04},
  "inverter_kw": 6.0, "estimated_installation": false, "approximate_location": false,
  "weather_fetched_at": "2026-11-24T14:20:03Z", "notes": [], "interval_minutes": 15,
  "intervals": [{"start": "2026-11-24T23:00:00Z", "kwh": 0.0, "basis": "weather"}]
}
```

- `basis`: skąd pogoda, czyli `weather`, `recent_days` (średnia z ostatnich dni) albo `mixed`.
- `complete`: każdy kwadrans ma pogodę albo zastępczą średnią.

Dla dni z przeszłości prognoza mówi, ile mogły dać panele przy pogodzie z archiwum. Można ją porównać
z plikiem.

Kod korzystający z prognozy, np. plan na jutro, wywołuje
`PvForecastService(weather, devices).forecast(user_id, profile, day)` i dostaje `PvForecast`.

## Ekran „Fotowoltaika” (ZP-150)

Ekran `/pv` (menu „Fotowoltaika”) i karta „Jutro z paneli” na dashboardzie. Kod: `backend/app/services/pv_insights.py`,
`frontend/src/pages/PvPage.jsx`.

| Część ekranu | Co pokazuje | Endpoint |
|---|---|---|
| Nagłówek | Panele z profilu, falownik, rozliczenie, czy prognoza jest dopasowana do plików i jak bardzo się myli | `GET /api/v1/pv/overview` |
| Najbliższe dni | Dziś, jutro, pojutrze: suma kWh, średnie zachmurzenie w godzinach ze słońcem, najniższa i najwyższa temperatura doby | `GET /api/v1/pv/overview` |
| Doba | Wykres co 15 min: produkcja z prognozy albo z modelu (dni minione: pogoda z archiwum), produkcja z pliku, zużycie domu, pasek zachmurzenia; pod spodem bilans i wartość | `GET /api/v1/pv/day?date=` |
| Trafność | Produkcja z pliku obok modelu w kolejnych dniach (ostatnie 60), kliknięcie otwiera dzień; `days_without_weather` mówi, dla ilu dni pogoda z archiwum jeszcze się pobiera | `GET /api/v1/pv/accuracy` |

Doba może być dowolnym dniem od 2000-01-01 do dziś + 2 dni. Dane z plików bierzemy tylko dla dni minionych; dziś
i kolejne dni to prognoza, nawet jeśli plik sięga dalej.

Ekran nie ma wyboru pliku: zawsze łączy wszystkie gotowe pliki. Pliki urządzeń łączymy jak „Wszystkie pliki
urządzeń” (kwadrans urządzenia z najnowszego pliku, który je zawiera), więc ten sam plik wgrany dwa razy nie liczy
się podwójnie. Pliki licznika łączymy jak „Wszystkie pliki” (przy nakładaniu wygrywa nowszy). Dzień z danymi
urządzeń bierze je z urządzeń, a pozostałe dni z licznika.

**Zużycie domu** w kwadransie:

| Dzień | Źródło (`consumption_source`) | Wzór |
|---|---|---|
| Miniony, z pliku urządzeń | `devices` | suma urządzeń poza falownikiem; produkcja to falownik z pliku (gdy falownik jest w pliku z tego okresu, brak jego wpisów to 0, np. śnieg), a bez falownika model |
| Miniony, tylko licznik | `meter` | pobór − oddanie + produkcja z modelu, nie mniej niż pobór |
| Miniony, licznik bez żadnego oddania w całym pliku | `meter_without_pv` | sam pobór: plik jest sprzed paneli, a produkcja i bilans pokazują, ile dałyby panele |
| Miniony bez odczytów | brak | nie pokazujemy zużycia ani bilansu, tylko produkcję z modelu |
| Dziś albo przyszły | `typical` | średnia tej samej godziny zegarowej z ostatnich (do 28) dni z odczytami, nie starszych niż 60 dni, najpierw dni tego samego rodzaju (robocze albo weekend); pole `typical` mówi, z ilu i jakich dni |

Typowe zużycie jest takie samo dla wszystkich dni roboczych (i osobno weekendów), bo to ta sama średnia. Gdy
ostatnie odczyty są starsze niż 60 dni, zużycia nie szacujemy.

Godzina powtórzona przy zmianie czasu ma w odczytach jeden zsumowany kwadrans, który dzielimy po równo.

**Bilans** liczymy w godzinach jak operator: w każdej godzinie autokonsumpcja = min(produkcja, zużycie), reszta
produkcji to oddanie, a reszta zużycia to pobór z sieci.

**Wartość:**
- **Autokonsumpcja:** cena z sieci z taryfy z profilu (energia, dystrybucja zmienna, opłaty za kWh, VAT), czyli
  to, czego dom nie kupił.
- **Oddanie w net-billingu:** RCE albo RCEm × 1,23 do depozytu, a ujemna cena daje 0. Bez cen z tego dnia
  bierzemy średnią z tych samych godzin z 14 poprzednich dni (z dopiskiem), a bez żadnych cen oddania nie
  wyceniamy.
- **Oddanie w net-meteringu:** współczynnik opustu × cena z sieci.

Depozyt pokrywa tylko część rachunku za energię, co ekran mówi wprost. Godziny bez ceny z sieci (umowa z ceną
dynamiczną przed publikacją RCE) są pomijane z dopiskiem.

Ekran czyta bazę, więc ma osobny, wysoki limit zapytań (`RATE_LIMIT_PV_SCREEN`, 300 na minutę), a przeglądanie
dni strzałkami go nie wyczerpie. Zapytanie użytkownika pobiera z Open-Meteo ten sam brakujący zakres pogody
najwyżej raz na 5 minut. Bez tego dzień, którego archiwum jeszcze nie ma, pytałby o niego przy każdym kliknięciu.

Typowe zużycie jest zapamiętywane w procesie na godzinę, tak jak kalibracja. Czasy odpowiedzi na roku danych:
- doba miniona: ok. 0,1 s;
- doba z typowym zużyciem: ok. 0,3 s przy pierwszym zapytaniu, potem szybciej;
- przegląd: ok. 0,1 s;
- trafność: ok. 0,4 s.

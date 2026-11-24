# Pogoda (ZP-117)

Pogoda do prognozy PV (ZP-118), pompy ciepła (ZP-119), dnia referencyjnego (ZP-120) i planu na jutro (ZP-121).
Źródło: Open-Meteo, bez klucza. Współrzędne domu pochodzą z profilu (`base_info.location`, ZP-116).

## Dlaczego w bazie

| Dane | Po co | Dlaczego zapisane |
|---|---|---|
| Historia (dni z wgranych plików) | Kalibracja modelu PV na prawdziwej produkcji, dzień referencyjny, symulacja dni z pliku | Nie zmienia się; potrzebna wiele razy, także gdy Open-Meteo nie odpowiada |
| Prognoza na dziś i dwa kolejne dni | Plan na jutro, ekrany | Plan musi powstać, gdy Open-Meteo nie działa; `fetched_at` mówi, z której prognozy liczył; ekrany nie czekają na zewnętrzne API |

Wiersze są dla komórki siatki ok. 0,1° (zaokrąglone współrzędne), nie dla użytkownika: modele pogody i tak mają
rozdzielczość kilku km, a sąsiednie domy korzystają z jednego pobrania. Tabela nie ma `user_id`.

## Tabela `weather_observations`

| Kolumna | Opis |
|---|---|
| `latitude`, `longitude` | Komórka siatki (0,1°) |
| `source` | `forecast` (Forecast API, co 15 min) albo `archive` (Archive API, co godzinę) |
| `interval_start`, `interval_minutes` | Początek okresu w UTC i jego długość (15 albo 60 min) |
| `ghi_w_m2` | Promieniowanie całkowite na poziomą powierzchnię, średnia z okresu |
| `tilted_w_m2` | Promieniowanie na płaszczyznę paneli: `{"35/0": 512.3, "20/-90": 210.0}`, klucz `nachylenie/azymut` (0 = południe, −90 = wschód) |
| `temperature_c`, `cloud_cover_pct` | Temperatura 2 m i zachmurzenie na początku okresu |
| `fetched_at` | Kiedy pobraliśmy dane |

Open-Meteo podaje promieniowanie jako średnią z okresu kończącego się w znaczniku czasu, więc zapisujemy je
z początkiem tego okresu (wartość z 13:00 to okres 12:00–13:00). Temperatura i zachmurzenie są chwilowe, więc
dostają okres zaczynający się w znaczniku. Bez tego produkcja PV byłaby przesunięta o kwadrans albo godzinę.

Open-Meteo przyjmuje jedno nachylenie i azymut na zapytanie, więc każda płaszczyzna paneli w komórce to osobne
zapytanie (wysyłane równolegle), a wyniki łączymy w `tilted_w_m2`. Temperaturę, zachmurzenie i GHI pobiera tylko
pierwsze z nich. Płaszczyzny, które są tą samą powierzchnią, pytamy raz: panele poziome (0°) mają zawsze azymut 0,
a −180° to 180°. Nowa płaszczyzna (zmiana paneli w profilu) jest dopisywana do istniejących wierszy. Brak wartości
w nowej odpowiedzi nie kasuje wartości zapisanej wcześniej.

## Dla jakich dni

| Dni | Skąd | Kiedy |
|---|---|---|
| Dziś i dwa kolejne dni | Forecast API (`minutely_15`) | Worker co 3 h; odczyt, gdy prognoza ma ponad 3 h |
| Dni z wgranych plików (od `data_start` do `data_end` każdego pliku) | Archive API (godzinowo) | Po imporcie pliku, po zapisie profilu i przez worker o 2:40 i 14:40 |
| Inny dzień z przeszłości (np. plan demo na dzień z przeszłości) | Archive API, cały miesiąc tego dnia naraz | Przy pierwszym odczycie tego dnia |

Historii nie pobieramy ciągiem od pierwszego pliku do dziś. Kolejne zadania potrzebują jej tylko dla dni z danymi
domu: kalibracja PV porównuje pogodę z produkcją z pliku (ZP-118), pompa ciepła zużycie z temperaturą (ZP-119),
dzień referencyjny wybiera podobny dzień spośród dni z pliku (ZP-120), a symulacja odtwarza dni z pliku. Plan na
dowolny dzień dostaje pogodę przez odczyt doby, który sam dociąga brakujący miesiąc. Prognozy z minionych dni
nie są pomiarem: dla przeszłości odczyt woli archiwum.

Szczegóły źródeł:

- Archive API ma dane do dziś, ale ostatnich dni są tymczasowe (ERA5 dochodzi z kilkudniowym opóźnieniem).
  Archiwum dnia pobrane wcześniej niż 6 dni po jego końcu worker pobiera jeszcze raz, raz, gdy minie 6 dni.
- Dzień bez archiwum (puste wartości) bierzemy z Forecast API, ale tylko do 60 dni wstecz: starszych dni
  Forecast API już nie ma (sprawdzone: ok. 70 dni, potem same puste wartości).
- Odczyt doby woli archiwum dla przeszłości i prognozę dla dziś i jutra; godzina z archiwum wypełnia cztery
  kwadranse. Gdy wiersz nie ma którejś płaszczyzny paneli, bierzemy kwadrans z drugiego źródła, jeśli ono ją ma.
- Doba ma 92, 96 albo 100 kwadransów (zmiana czasu), liczonych w strefie Europe/Warsaw.
- Doba, której nie da się uzupełnić (np. luka w archiwum), ma kwadranse bez wartości i `complete: false`.

## Zmiana lokalizacji albo paneli

Zapis profilu uruchamia w tle pobranie dla domu: prognozę (tylko gdy jej brakuje, jest starsza niż 3 h albo nie
ma nowej płaszczyzny paneli) i historię dla dni z plików. Nowa lokalizacja to zwykle nowa komórka siatki, więc
pogoda dla niej jest w bazie po kilku sekundach (sprawdzone na żywo: zmiana adresu na Wronki pobrała prognozę
i historię 2025–2026). Wiersze starej komórki zostają: nie są przypisane do użytkownika i mogą służyć sąsiednim
domom. Nowa płaszczyzna paneli jest dopisywana do wierszy komórki (`tilted_w_m2`), stare zostają.

## Kiedy pobieramy

| Kiedy | Co |
|---|---|
| Worker `weather-worker`, co 3 h (xx:20) i przy starcie | Prognoza dla komórek domów z PV albo z wgranym plikiem |
| Worker, o 2:40 i 14:40 | Brakująca historia dla dni z plików i ponowne pobranie archiwum tymczasowego |
| Worker, o 3:50 i przy starcie | Usuwa prognozy starsze niż 100 dni (dla przeszłości jest już archiwum) |
| Po imporcie pliku (zadanie w tle po odpowiedzi) | Historia dla dni z plików tego użytkownika |
| Po zapisie profilu (zadanie w tle) | Prognoza i historia dla domu użytkownika |
| `GET /api/v1/weather/forecast?date=` | Doba, której nie ma w bazie (cały miesiąc albo dziś i dwa dni naprzód), albo prognoza starsza niż 3 h |

Zadania workera idą jedno po drugim (jeden wątek), więc długa historia nie powoduje pominięcia prognozy, a blokada
doradcza PostgreSQL chroni przed drugim procesem workera. Przy starcie worker od razu pobiera prognozę, historię
i usuwa stare prognozy, więc nie musi działać całą dobę: wystarczy uruchomić aplikację. W workerze błąd sieci i 5xx
są ponawiane (3 próby, 2 s i 4 s przerwy); endpoint pyta raz z limitem 8 s, żeby użytkownik nie czekał. Limit
zapytań (429) i błędne zapytanie nie są ponawiane. Błąd jednej komórki albo jednego profilu nie zatrzymuje
pozostałych. Gdy Open-Meteo nie odpowiada, odczyt zwraca to, co jest w bazie, a bez danych endpoint odpowiada 503.

Profil z lokalizacją przybliżoną (`approximate`) worker przed pobraniem próbuje wyznaczyć ponownie (jak odczyt
profilu w ZP-116). Profil w starym formacie (do uzupełnienia) jest pomijany. Profili bez PV i bez wgranych plików
worker nie czyta wcale (wybiera je zapytaniem do bazy), więc dla nich nie pyta też geokodera.

```
python -m app.workers.weather_worker forecast   # jednorazowo prognoza
python -m app.workers.weather_worker history    # jednorazowo historia dla plików
```

## API

`GET /api/v1/weather/forecast?date=RRRR-MM-DD` (domyślnie dziś, od 2000-01-01 do dziś + 2 dni) zwraca pogodę
komórki domu zalogowanego użytkownika:

```json
{
  "date": "2026-11-24", "latitude": 51.1, "longitude": 17.0, "location_approximate": false,
  "interval_minutes": 15, "planes": [{"tilt": 35, "azimuth": 0}],
  "fetched_at": "2026-11-23T14:20:03Z", "complete": true,
  "intervals": [{"start": "2026-11-23T23:00:00Z", "source": "forecast", "temperature_c": 1.4,
                 "cloud_cover_pct": 85, "ghi_w_m2": 0.0, "tilted_w_m2": [0.0]}]
}
```

`tilted_w_m2` ma wartości w kolejności `planes`. Profil bez PV ma puste `planes`. `complete: true` oznacza, że każdy
kwadrans ma GHI i promieniowanie na każdą płaszczyznę z `planes`, czyli komplet do prognozy PV; brak promieniowania
choćby jednej grupy paneli (np. świeżo dodanej, gdy Open-Meteo nie odpowiada) daje `false`. Brak profilu: 404, doba spoza
zakresu: 422, brak danych i niedostępne Open-Meteo: 503.

Open-Meteo w darmowej wersji jest do użytku niekomercyjnego (limit 10 000 zapytań na dobę). Odczyt na żądanie
pobiera cały miesiąc naraz, więc przeglądanie dowolnych dni kosztuje najwyżej jedno zapytanie na miesiąc i płaszczyznę.
Endpoint ma limit prób na adres IP, domyślnie 30 na minutę (`RATE_LIMIT_WEATHER`), żeby przeklikiwanie dat nie zużyło
limitu Open-Meteo wspólnego dla całej aplikacji i workera. Adresy można zmienić
przez `OPEN_METEO_FORECAST_URL` i `OPEN_METEO_ARCHIVE_URL`. Testy używają klienta offline (`tests/conftest.py`).

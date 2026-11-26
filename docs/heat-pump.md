# Pompa ciepła a temperatura (ZP-119)

Ile prądu zużyje pompa ciepła w dniu planu przy prognozowanej temperaturze. Kod:
- `backend/app/services/heat_pump_model.py`: model, bez bazy, używany też przez generator plików;
- `backend/app/services/heat_pump.py`: dopasowanie do plików i pogody, skalowanie bloków w planie.

## Model

Ciepło potrzebne domowi w dobie to ogrzewanie i ciepła woda:

```
ciepło  = ciepło_na_stopniodzień × stopniodni + ciepła_woda
prąd    = ciepło_na_stopniodzień × stopniodni / COP_ogrzewania(T) + ciepła_woda / COP_wody(T)
```

**Stopniodni** liczymy jak Eurostat: 18 °C − średnia temperatura doby, gdy średnia nie przekracza 15 °C,
a powyżej 15 °C zero. Temperatura to średnia z kwadransów doby z pogody (ZP-117): archiwum dla dni minionych,
prognoza dla dnia planu.

**COP pompy powietrznej** liczymy jak w When2Heat (Ruhnau, Hirth, Praktiknjo 2019, Scientific Data 6:189; kod
`oruhnau/when2heat`, `scripts/cop.py`):

```
COP = 0,85 × (6,08 − 0,0941·ΔT + 0,000464·ΔT²),  ΔT = temperatura wody − temperatura powietrza, najmniej 15 K
```

- Temperatura wody z krzywej grzewczej: ogrzewanie podłogowe 30 − 0,5·T, grzejniki 40 − T, ciepła woda 50 °C.
- 0,85 to straty w praktyce: odszranianie i pompy obiegowe.
- Profil nie mówi, jaką instalację ma dom. Domy od 2000 roku traktujemy jak dom z podłogówką, starsze jak dom
  z grzejnikami.

| Temperatura | COP podłogówki | COP grzejników | COP ciepłej wody |
|---|---|---|---|
| 10 °C | 4,1 | 3,7 | 2,6 |
| 0 °C | 3,1 | 2,6 | 2,2 |
| −10 °C | 2,4 | 1,8 | 1,8 |

## Skąd znamy dom

1. **Z plików (`source = history`).** Zużycie pompy (`heat_pump`) na dobę z plików urządzeń (bez wersji przykrytych
   nowszym plikiem) i średnia temperatura tych dni z bazy. Metodą najmniejszych kwadratów dopasowujemy dwie
   liczby: ciepło na stopniodzień i ciepłą wodę na dobę (obie nieujemne).
   - Pomijamy dni bez pracy pompy (poniżej 0,2 kWh, np. wyjazd).
   - Odrzucamy dni, które odbiegają od dopasowania o ponad połowę i co najmniej 2 kWh, a potem dopasowujemy jeszcze raz.
   - Potrzeba co najmniej 10 dni, w tym 7 z ogrzewaniem.
   - Błąd (`mape`) liczymy metodą „bez jednego dnia” na dniach z ogrzewaniem.
2. **Profil i pliki (`mixed`).** W plikach jest za mało zimnych dni (np. tylko lato): ogrzewanie z profilu,
   a ciepła woda z plików.
3. **Profil (`building`).** Za mało historii.
   - Ciepło na stopniodzień = zapotrzebowanie na m² według roku budowy × metraż / 3300 (stopniodni typowego roku
     w Polsce; Wrocław 2026 z archiwum Open-Meteo: ok. 3100).
   - Ciepła woda = 1,6 kWh na osobę na dobę (jak w modelu bojlera) × 1,2 na straty zasobnika. Gdy dom ma bojler
     elektryczny, pompa grzeje tylko dom.

| Rok budowy | Ciepło na ogrzewanie (kWh/m² rocznie) |
|---|---|
| do 1966 | 290 (zakres 240–350) |
| 1967–1985 | 260 (240–280) |
| 1986–1992 | 180 (160–200) |
| 1993–1997 | 140 (120–160) |
| 1998–2008 | 105 (90–120) |
| 2009–2013 | 85 (założenie, WT2008) |
| 2014–2020 | 65 (założenie, WT2014/2017) |
| od 2021 | 45 (założenie, WT2021) |

Dla domów do 2008 roku wartości to środki zakresów z polskich zestawień energochłonności budynków
mieszkalnych. Dla nowszych to założenia z wymagań warunków technicznych. Nie wiemy, czy dom był ocieplany,
dlatego historia z plików wygrywa z profilem.

Dom 120 m² z 2010 roku z 3 osobami: ok. 3,1 kWh ciepła na stopniodzień i 5,8 kWh na wodę.

| Średnia temperatura doby | Prąd pompy na dobę |
|---|---|
| 5 °C | ok. 14 kWh |
| 0 °C | ok. 20 kWh |
| −10 °C | ok. 40 kWh |

W roku to ok. 3,9 tys. kWh.

## Plan na jutro

Plan (`plan_service._heat_pump`) bierze godziny grzania z dnia referencyjnego, czyli ostatniego dnia z historią
pompy, i zmienia ilość energii według pogody:

```
energia = zużycie dnia referencyjnego + model(dzień planu) − model(dzień referencyjny)
```

Różnicę liczymy z modelu, a poziom bierzemy z prawdziwego dnia, więc zostają zwyczaje domu, np. wieczorna
kąpiel. Energia nie spada poniżej połowy tego, co daje model dla dnia planu.

Bloki skalujemy proporcjonalnie (`scale_blocks`):
- Blok, który przy mocy pompy (`max_power_kw` × 0,25 h na kwadrans) nie zmieści energii, wydłuża się do następnego
  bloku albo do końca planu (06:00).
- Czego i tak się nie da, przepada, a plan ostrzega, że w domu może być chłodniej.

| Sytuacja | Co robi plan |
|---|---|
| Brak pogody na dzień planu albo dzień referencyjny | Energia jak w dniu referencyjnym, z dopiskiem dlaczego |
| Profil bez lokalizacji albo metrażu i za mało historii | Jak przed ZP-119: energia z dnia referencyjnego |

Odpowiedź planu ma `heat_pumps`:
- temperatura dnia planu i dnia referencyjnego;
- ciepło dla domu i jego część na wodę;
- stopniodni i COP;
- energia: cel (`target_kwh`) i to, co się zmieściło (`kwh`);
- skąd model zna dom.

Ekran planu pokazuje to na karcie „Ogrzewanie”.

Wykonanie planu w symulacji (ZP-113) wysyła pompie profil z planu, więc też jest dopasowane do pogody. Pompa
odznaczona w planie (pracuje sama na termostacie) i produkcja PV w symulacji to dalej dzień referencyjny (ZP-120).

## Generator plików

`generate_devices_file.py` liczy pompę z tego samego modelu. Dom opisują `--area-m2`, `--year-built`
i `--residents` (domyślnie 120 m², 2010, 3 osoby).

- **Temperatura:** godzinowa z `--weather` (także bez PV), a bez niego średnia miesiąca dla Polski z losową
  odchyłką doby (ciepłe i zimne okresy trwają kilka dni) i rytmem dobowym.
- **Ogrzewanie:** rozłożone na kwadranse według tego, jak zimno jest w danej chwili, a COP liczony z temperatury
  kwadransu.
- **Ciepła woda:** rano i wieczorem.
- **Losowość:** ±12% na ogrzewanie, ±15% na wodę.
- **Bloki:** 4 na dobę (od 0, 6, 12 i 18), przycięte do mocy pompy i limitu przyłącza.
- **Moc pompy:** 4,5 kW albo więcej dla większych i starszych domów.
- **Losowanie:** pompa ma osobne ziarno, więc pozostałe urządzenia są takie same jak przed ZP-119.

Plik demo (`devices_demo_30d.json`, październik we Wrocławiu):
- korelacja zużycia pompy z temperaturą doby: ok. −0,98;
- dopasowanie odtwarza dom z profilu z błędem kilku procent.

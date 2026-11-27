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

**Stopniodni** liczymy jak Eurostat: 18 °C − średnia temperatura doby, gdy średnia nie przekracza 15 °C.
Między 15 a 18 °C maleją płynnie do zera (parabola: 3 przy 15 °C, 0,75 przy 16,5 °C, 0 przy 18 °C), żeby średnia
15,1 °C nie dawała nagle zera zamiast 3 stopniodni. Temperatura to średnia z kwadransów doby z pogody (ZP-117):
archiwum dla dni minionych, prognoza dla dnia planu.

**Temperatura w domu.** Próg 18 °C odpowiada ok. 21 °C w domu (resztę dają ludzie, urządzenia i słońce). Inna
temperatura z ustawień pompy w planie przesuwa próg i granicę 15 °C o tyle samo stopni, np. 23 °C w domu to
20 °C − średnia doby. Każdy stopień cieplej to ok. 5–6% więcej ciepła na ogrzewanie. Dzień referencyjny liczymy
zawsze dla 21 °C, bo nie wiemy, jakie ustawienie było wtedy.

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
   - Dzień z ogrzewaniem to dzień o średniej do 15 °C (dni 15–18 °C mają tylko resztki stopniodni).
   - Odrzucamy dni, które odbiegają od dopasowania o ponad połowę i co najmniej 2 kWh, a potem dopasowujemy jeszcze raz.
   - Potrzeba co najmniej 10 dni, w tym 7 z ogrzewaniem.
   - Błąd (`mape`) liczymy metodą „bez jednego dnia” na dniach z ogrzewaniem.
2. **Profil i pliki (`mixed`).** W plikach jest za mało zimnych dni (np. tylko lato): ogrzewanie z profilu,
   a ciepła woda z plików.
3. **Profil (`building`).** Za mało historii.
   - Ciepło na stopniodzień = zapotrzebowanie na m² według roku budowy × metraż / 3300 (stopniodni typowego roku
     w Polsce; Wrocław 2026 z archiwum Open-Meteo: ok. 3100).
   - Ciepła woda = 1,6 kWh na osobę na dobę (jak w modelu bojlera) × 1,2 na straty zasobnika. Gdy w obecnych
     plikach (bez wersji przykrytych nowszym plikiem) pracuje bojler elektryczny, pompa grzeje tylko dom.

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

## Plan na jutro: temperatura w domu

Plan pilnuje temperatury w domu, a nie godzin grzania z wczoraj (`plan_service._heat_pump_indoor`,
`house_heating.py`). Dom to magazyn ciepła, jak zbiornik bojlera dla wody:

- **Straty ciepła** (kW na stopień różnicy temperatur) = ciepło na stopniodzień / 24 h, z modelu domu (z plików
  albo z profilu). Ludzie, urządzenia i słońce dają równowartość 3 °C (próg 18 °C przy 21 °C w domu), więc dom
  traci `straty × (w domu − na dworze − 3)` kW.
- **Pojemność cieplna** (kWh na stopień): ile ciepła trzeba, żeby ogrzać dom o 1 °C. Z plików jej nie poznamy, bo
  zużycie jest dobowe, więc przyjmujemy klasy z EN ISO 13790 według typu budynku z profilu: mieszkanie w bloku
  ciężkie (260 kJ/(m²·K), beton), dom wolnostojący i szeregowiec średnie (165), domek letniskowy lekki (110).
  Bez metrażu: stała czasowa 40 h. Dom 120 m² z 2010 roku ma stałą czasową ok. 43 h i przy 0 °C bez grzania
  stygnie o ok. 0,4 °C na godzinę.
- **Typ budynku a straty z profilu:** mieszkanie w bloku traci ok. 55% ciepła na m² domu wolnostojącego (sąsiedzi
  za ścianami, nad i pod), szeregowiec ok. 80% (dwie ściany wspólne). Gdy model jest z plików, straty wychodzą
  z dopasowania i typ budynku zmienia tylko pojemność.
- **Pompa** grzeje w kwadransie z mocą 0, połowy albo całej (pompy inwerterowe modulują moc), a ciepła daje COP
  razy więcej niż prądu; COP zależy od temperatury na dworze w tym kwadransie (pogoda co kwadrans).

Bez planu dom grzeje termostat: co kwadrans tyle, żeby wrócić do ustawionej temperatury. Plan wybiera najtańsze
kwadranse (programowanie dynamiczne jak w bojlerze), tak żeby w domu było od ustawionej − 1 °C do ustawionej
+ 1 °C, a na koniec doby wróciło do ustawionej (kolejny dzień zaczyna od tego samego). Dom może więc nagrzać się
na zapas w tanich godzinach i lekko ostygnąć w drogich. Limit przyłącza jest miękki, jak w bojlerze. Liczymy dobę
planu 00:00–24:00.

Najpierw planujemy ciepłą wodę (zasobnik, niżej), bo w jej kwadransach pompa nie grzeje domu. W domu bez bojlera
woda jest zawsze planowana osobno: na godziny z ustawień albo, bez nich, na 6:00 i 18:00.

Przy kilku pompach każda grzeje swoją część domu: udział w zużyciu pomp w dniu referencyjnym.

Odpowiedź planu ma `heat_pumps` z `mode = "indoor"`:
- temperatura doby planu, zakres w domu (`band`) i niedogrzanie poniżej zakresu (`shortfall`);
- prąd: według planu (`kwh`, z wodą) i ogrzewanie bez planu (`thermostat_kwh`);
- o ile °C na godzinę dom stygnie bez grzania (`cooling_per_hour`) i stała czasowa domu;
- temperatura w domu kwadrans po kwadransie według planu i bez planu (`temperatures`);
- ciepło dla domu i wody, stopniodni, COP i skąd model zna dom.

Ekran planu pokazuje to na karcie „Ogrzewanie”: najpierw wniosek (pogoda, zakres w domu, prąd), a wykres
temperatury w domu, ciepło, wodę, COP i trafność dopasowania pod „Jak to liczymy”. Gdy dopasowanie z plików myli
dobowe zużycie o ponad 20%, karta mówi, że prognoza jest orientacyjna.

### Bez pogody albo modelu domu

Gdy nie ma pogody na dobę planu, lokalizacji domu albo modelu (brak metrażu w profilu i historii), plan działa
jak przed modelem domu (`mode = "history"`): bierze godziny grzania z dnia referencyjnego, czyli ostatniego dnia
z historią pompy, i zmienia ilość energii według pogody:

```
energia = zużycie dnia referencyjnego + model(dzień planu) − model(dzień referencyjny)
```

Bloki skalujemy proporcjonalnie (`scale_blocks`) i każdy można przesunąć najwyżej o `shift_hours` (z pliku albo
1 h). Blok, który przy mocy pompy nie zmieści energii, wydłuża się do następnego bloku albo do końca planu.

| Sytuacja | Co robi plan |
|---|---|
| Brak pogody na dzień planu | Energia jak w dniu referencyjnym, z dopiskiem dlaczego |
| Profil bez lokalizacji albo metrażu i za mało historii | Energia z dnia referencyjnego |

### Ciepła woda gotowa na…

W domu bez bojlera w ustawieniach pompy można podać godziny, na które ciepła woda ma być gotowa (jak przy
bojlerze). W domu z bojlerem (w obecnych plikach) wodę grzeje bojler, więc ekran o to nie pyta, a planer
pomija takie godziny. W planie bez pogody (wyżej) bez godzin
woda grzeje się jak w dniu referencyjnym, w blokach razem z domem. Z godzinami plan liczy ją osobno, tym samym
modelem zbiornika co bojler (`water_heater.py`):

- zasobnik 200 l (albo pojemność z ustawień), woda 40–55 °C, na godziny gotowości co najmniej 50 °C
  (`HEAT_PUMP_TANK`; pompa nie grzeje wody do 75 °C jak grzałka);
- kwadrans grzania wody to pełna moc pompy, a ciepła jest COP wody razy więcej, więc koszt ciepła to cena prądu
  przez COP;
- pobór wody na dobę z modelu domu (ciepło na wodę bez strat zasobnika, które liczy symulacja zbiornika);
- woda omija kwadranse ponad limitem przyłącza (a w planie bez pogody także te, w których pompa grzała dom
  w dniu referencyjnym), chyba że inaczej byłaby za zimna.

W planie z temperaturą w domu pompa w kwadransach grzania wody nie grzeje domu. W planie bez pogody bloki
ogrzewania dostają cel bez części na wodę z modelu. Pompa nie grzeje domu i wody naraz: blok, który
nachodziłby na grzanie wody, ma w tych kwadransach przerwę i wydłuża się o tyle dalej, a bloku z przerwami plan
nie przesuwa.

Wykonanie planu w symulacji (ZP-113) wysyła pompie profil z planu, więc też jest dopasowane do pogody. Pompa
odznaczona w planie (pracuje sama na termostacie) też jest dopasowana do temperatury, tą samą funkcją
(`day_background.py`, ZP-120): przebiegi dnia referencyjnego zachowują kształt, a nadmiar przy mocy pompy
wydłuża przebieg do następnego albo do końca doby. To, o ile pobierze więcej niż w dniu referencyjnym, plan
dolicza do zapasu w limicie przyłącza.

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

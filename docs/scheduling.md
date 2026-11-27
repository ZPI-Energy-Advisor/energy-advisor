# Harmonogramowanie akcji urządzeń

`backend/app/services/scheduling.py` rozmieszcza akcje urządzeń tak, żeby koszt przy cenach
kwadransów był najmniejszy. To czysta funkcja, bez bazy i bez wiedzy o taryfach. Ta sama służy do
poprawy historycznego okresu i do planu na przyszłość: różni je tylko to, skąd pochodzą akcje i ceny.

```python
schedule(actions, prices, max_grid_kw=None) -> ScheduleResult
```

- `actions`: lista `ScheduleAction`; z pliku urządzeń buduje ją `actions_from_devices`.
- `prices`: słownik początek kwadransa (UTC) → cena za kWh. Dziś ceny taryfy dynamicznej.
- `max_grid_kw`: limit przyłącza; `None` go wyłącza. Ekran Optymalizacja podaje moc umowną z profilu.

Obsługiwane są tryby `fixed`, `shiftable` i `interruptible` (ładowanie EV).
Produkcja PV nie trafia na wejście, bo w wycenie nie pomniejsza zużycia.

## Ładowanie EV (`interruptible`)

Sesja ładowania ma energię i okno: od `plugged_in` do `deadline` z pliku, także po końcu
analizowanego okresu, bo energia sesji należy do doby, w której się zaczęła. `allowed_window`
ładowarki nie ogranicza sesji: okno sesji to faktyczny czas podłączenia auta.

Energię sesji dzielimy na najtańsze kwadranse okna (przy równej cenie na wcześniejsze). Kwadrans
przyjmuje najwyżej `max_power_kw × 0,25 h` (bez mocy urządzenia: najmocniejszy kwadrans sesji)
i tyle, ile zostało pod `max_grid_kw`. Plan może mieć przerwy; wynik zwraca go jako profil od
pierwszego kwadransu ładowania z zerami w przerwach, a oryginał w `original_profile_kwh`.
Plan, który nie jest tańszy od oryginału (np. przy płaskiej cenie), zostaje jak w pliku.

## Obciążenie domu i limit przyłącza

Limit liczymy jak licznik: pobór z sieci to zużycie pracujących urządzeń minus bieżąca produkcja PV.
Akcje `load_only` tylko obciążają dom: produkcja PV z pliku (ujemna) oraz akcje z doby przed i po
okresie (urządzenia pracujące, gdy akcja z poprzedniej doby trwa po północy albo ładowanie EV sięga
za koniec okresu). Nie przesuwają się, nie mają kosztu i nie trafiają do wyniku. Ekran Optymalizacja
podaje jako limit moc umowną z profilu.

Rachunek „przed” i „po” liczy te same kwadranse: okres i jego ogon do końca najpóźniejszej akcji,
z zerami tam, gdzie brakuje odczytów, żeby żaden nie dostał dodatkowej doby opłat stałych.

Sesje układamy po wszystkich grupach, bo są najbardziej elastyczne i dopasowują się do reszty
domu. Sesja, której energia nie mieści się w oknie pod limitem, zostaje w oryginalnym kształcie
jako konflikt `grid_limit`; sesja bez cen oryginału zostaje bez zmian (`missing_prices`).

## Reguły

Akcje `fixed` zostają bez zmian. Akcja `shiftable` przesuwa się w całości, z tym samym profilem.
Start jest dozwolony, gdy:

1. wypada co 15 minut;
2. wypada tej samej doby lokalnej co oryginalny, koniec może być po północy. Dzięki temu akcje
   z różnych dni nie zbijają się w jeden tani dzień;
3. mieści się w `max_shift_min` w obie strony, jeśli akcja ma to pole;
4. cała akcja leży w `allowed_window`, a start zostaje w tym samym wystąpieniu okna co oryginał.
   Okno 19:00–7:00 obejmuje też 3:00 tego samego dnia, ale to poprzednia noc;
5. kwadranse nie są zajęte przez inną akcję tego samego urządzenia;
6. wszystkie kwadranse mają cenę;
7. łączny pobór domu w żadnym kwadransie nie przekracza `max_grid_kw`.

Okno jest twardą regułą: akcja, która w historii była poza oknem, jest do niego wciągana, nawet
jeśli wyjdzie drożej.

## Kolejność układania

1. Akcje łączymy w grupy. `after_action_id` wiąże akcję z poprzednią: obie przesuwają się o to samo,
   więc zachowują kolejność i odstęp. `actions_from_devices` wiąże suszarkę z praniem, jeśli startuje
   najwyżej 60 minut po jego końcu. Grupa z akcją `fixed` zostaje na miejscu.
2. Grupy układamy od największej energii, bo oszczędność to energia razy różnica cen.
3. Dla każdej grupy sprawdzamy dozwolone przesunięcia i wybieramy najtańsze. Przy równym koszcie
   wygrywa start najbliższy oryginalnemu, więc przy płaskich cenach nic się nie rusza.
4. Powtarzamy przebiegi, aż nic się nie zmieni (najwyżej 3), bo przesunięcia zwalniają miejsca.

Układamy bez rezerwowania miejsc grup, które czekają na swoją kolej: duża akcja powinna móc zająć
miejsce małej. Jeśli przez to jakaś grupa nie ma dokąd pójść, układamy wszystko od nowa, rezerwując
oryginalne miejsca. Wtedy każda grupa ma przynajmniej swoje miejsce.

## Wynik

Dla każdej akcji: nowy start i koniec, profil, koszt przed i po oraz `status`:

| `status` | Znaczenie |
|---|---|
| `moved` | akcja się przesunęła |
| `unchanged` | zostaje: to już najlepsze miejsce albo akcja `fixed` |
| `conflict` | zostaje mimo problemu, powód w `reason` |

Powody konfliktu: `outside_window` (poza oknem, brak dozwolonego startu), `missing_prices`
(brak cen na oryginalnym miejscu; akcja nie wchodzi do sum kosztów), `grid_limit` (limit przyłącza).

Lista akcji jest też planem dla huba: urządzenie, program, start.

## Podgląd

```bash
python backend/scripts/show_schedule.py backend/tests/fixtures/scheduling_demo.json \
    backend/tests/fixtures/scheduling_demo_prices.json
python backend/scripts/show_schedule.py plik.json ceny.json --max-grid-kw 9 --out wynik.json
```

Ceny w `scheduling_demo_prices.json` są przykładowe i mają tylko typowy kształt: tanio w południe,
drogo wieczorem. Przykładowy wynik w JSON, dla ekranu optymalizacji i huba:
`backend/tests/fixtures/scheduling_demo_result.json`.

## API i ekran

`GET /api/v1/energy-files/{id}/schedule?from=RRRR-MM-DD&to=RRRR-MM-DD` liczy optymalizację dla akcji
pliku urządzeń z wybranych dni, przy cenach dla klienta taryfy dynamicznej (`ScheduleResponse`).
Bez `from` i `to` bierze cały okres pliku. Ceny są czytane z bazy przy każdym zapytaniu.

Odpowiedź poza akcjami i cenami ma `missing_price_actions` i `missing_price_days`: liczbę akcji bez cen
na oryginalnym miejscu i ich doby lokalne. Takie akcje zostają (`conflict`, `missing_prices`) i nie
wchodzą do `cost_before` ani `cost_after`, więc wynik jest wtedy niepełny.

Błędy:

| Kod | Kiedy |
|---|---|
| 404 | plik nie istnieje albo należy do innego użytkownika; brak taryfy dynamicznej w bazie |
| 422 | zły zakres dat; w okresie nie ma akcji poboru energii (np. plik licznika albo sama produkcja PV); brak cen dla wszystkich akcji |

Korzysta z niego zakładka „Optymalizacja”: dla każdej doby pokazuje ceny oraz akcje urządzeń przed i po.
Działa tylko dla pojedynczego pliku urządzeń; dla pliku licznika i plików zbiorczych zakładka pokazuje
komunikat zamiast formularza. Brak cen opisuje jedną notką z listą dni, a nie przy każdej akcji.

## Założenia

- Wynik dla historii zakłada, że z góry wiadomo, jakie akcje będą danego dnia. Ceny na dany dzień są
  znane z wyprzedzeniem, bo PSE publikuje je dzień wcześniej.
- Czas jest liczony w UTC, a okna i doby w czasie lokalnym (`Europe/Warsaw`).

## Wymagania na jutro (ZP-111)

Wejście do planu na jutro podaje każdy zalogowany użytkownik dla urządzeń ze swoich plików
(bez huba Smart Home): `GET` i `PUT /api/v1/planning/preferences`. Planować można urządzenia
`shiftable` i `interruptible` z programami, ładowarkę EV oraz pompę ciepła (`heat_pump`) i bojler
(`water_heater`): pompę plan układa z historii, a bojler z temperatury wody i poboru ciepłej wody
z historii albo z liczby osób (ZP-112). Inne elastyczne urządzenie bez
programów jest pomijane, bo samo „pracuje jutro” nie mówi, ile ma pracować.
Ustawienia (tabela `planning_templates`, jeden zestaw na konto) zostają do kolejnego zapisu, który
je nadpisuje. Plan zawsze szuka najtańszego miejsca w przedziałach.

`GET` zwraca urządzenia z programami, domyślnymi przedziałami (`allowed_window` z pliku, bez okna
cała doba) i preferencją: zapisaną albo domyślną (`enabled: false`; pompa ciepła i bojler od razu
`enabled: true`, bo i tak pracują codziennie). Każde urządzenie ma `kind`: `program`, `ev`, `heat_pump`
albo `water_heater`; pompa ma też `history_kwh` i `history_day`, a bojler `residents` (z profilu,
bez profilu 2), `hot_water_kwh` (ciepła woda na dobę), `hot_water_source` (`history` albo `residents`)
i `history_kwh` (średnie zużycie bojlera na dobę z 7 ostatnich dni w plikach).
`PUT` przyjmuje `{devices: [...]}` i odpowiada tym samym kształtem co `GET`.

| Pole preferencji | Opis |
|---|---|
| `enabled` | Czy urządzenie pracuje jutro; wyłączone zachowuje ustawienia bez sprawdzania |
| `program_id` | Program z programów urządzenia (wymagany, gdy urządzenie ma programy) |
| `windows` | 1–4 przedziały `{start, end}` co kwadrans (`HH:MM`); koniec nie później niż start przechodzi przez północ, `00:00–00:00` to cała doba. Urządzenie kończy pracę przed końcem swojego przedziału |
| `after_device_id` | „Wykonaj po”: urządzenie z programem rusza po końcu programu innego włączonego urządzenia z programem (np. suszarka po pralce), najwyżej 60 min później (`DRYER_AFTER_WASH`); plan przesuwa je razem jak suszarkę z pralką w pliku. Start wyznacza poprzednik, więc `windows` takiego urządzenia nie są sprawdzane ani używane (zostają zapisane na wypadek usunięcia „Wykonaj po”) |
| `finish_by` | Tylko z `after_device_id`, opcjonalne: program kończy się najpóźniej o tej godzinie (`HH:MM` co kwadrans). Godzina nie późniejsza niż początek najwcześniejszego przedziału pierwszego urządzenia w łańcuchu oznacza rano następnego dnia |
| `energy_input`, `energy_kwh` | Ładowarka EV: energia wprost w kWh |
| `battery_kwh`, `current_percent`, `target_percent` | Ładowarka EV: energia z poziomu baterii; z sieci `(docelowy − obecny) × pojemność / 0,9` (straty ładowania). Pojemność zostaje w ustawieniach |
| `shift_hours` | Pompa ciepła: o ile godzin (1–3) w obie strony planer może przesunąć każdy blok grzania. Ekran o to nie pyta: wartość to `max_shift_min` z pliku albo 1 h |
| `indoor_temp_c` | Pompa ciepła: temperatura w domu 16–25 °C; bez wartości 21 °C ([heat-pump.md](heat-pump.md)) |
| `ready_times` | Bojler: 1–4 godziny „woda gotowa na” co kwadrans, bez powtórzeń; domyślnie `06:00` i `18:00`. `00:00` to północ na końcu doby. Pompa ciepła w domu bez bojlera: 0–4 godziny „ciepła woda z pompy gotowa na” (bez godzin woda grzeje się jak w dniu referencyjnym) |
| `tank_liters` | Bojler: pojemność zbiornika 30–500 l. Gdy plik urządzeń ma `tank_liters`, wygrywa wartość z pliku (`tank_liters_from_file`, ekran tylko ją pokazuje); bez niej domyślna z liczby osób: 80 l dla 1–2, 120 l dla 3–4, 150 l od 5 |

Błędy (`422`, lista z `loc: ["body", "devices", indeks, pole]`): przedziały nachodzące na siebie,
najdłuższy przedział krótszy niż program, brak programu, brak energii auta, docelowy poziom baterii
nie wyższy niż obecny i energia auta większa niż moc ładowarki × długość przedziałów. Dla „Wykonaj po”:
poprzednik nie pracuje jutro, pętla (urządzenia czekają na siebie nawzajem), urządzenie bez programu
oraz program, który nie zdąży przed `finish_by` nawet przy najwcześniejszym końcu poprzednika
(sprawdzane po całym łańcuchu, np. pralka → suszarka → trzecie urządzenie). Pompa ciepła: powtórzona
godzina ciepłej wody; bojler: brak godzin albo powtórzona godzina.

## Plan pracy urządzeń na jutro (ZP-112)

Plan powstaje z ustawień ZP-111 tym samym rdzeniem (`schedule`) i jest zapisywany (tabela `day_plans`,
jeden na użytkownika i dzień) ze statusem `draft` albo `approved`:

| Metoda i ścieżka | Opis |
|---|---|
| `POST /api/v1/planning/plans` | Układa plan na jutro (body `{}`) albo na `plan_date` (plan idealny dnia z przeszłości, plan demo). Nadpisuje plan tego dnia i wraca do `draft`; `201` z planem |
| `GET /api/v1/planning/plans/current` | Ostatni plan na jutro (`kind = tomorrow`, także plan demo) albo `null`; plan idealny go nie zasłania |
| `GET /api/v1/planning/plans?date=RRRR-MM-DD` | Plan na ten dzień albo `null` (widok „Wybrany dzień”) |
| `GET /api/v1/planning/past-days` | Zakres dni do planu idealnego: `first_day` (pierwszy dzień ze stawkami operatora, przy cenie dynamicznej też z RCE), `last_day` (wczoraj) i `file_periods` (okresy plików urządzeń) |
| `POST /api/v1/planning/plans/{id}/approve` | Zatwierdza plan (`approved`, `approved_at`); cudzy albo nieistniejący plan: `404` |

Ścieżka jest pod `/planning`, a nie `/home` jak w tickecie, bo plan (tak jak ustawienia) jest dla każdego
zalogowanego, bez domu Smart Home.

**Zakres planu**: od północy dnia planu do 06:00 następnego dnia (30 h), żeby zmywarka czy auto mogły
pracować przez północ. Przedziały sięgające dalej (np. auto 18:00–07:00) plan przycina do 06:00.
Zasada „start w tej samej dobie” nie obowiązuje: każda akcja ma jawne `allowed_starts`
(dla sesji `allowed_slots`) wyliczone z ustawień, a rdzeń sprawdza tylko je. Optymalizacja z plików
(okres historyczny) działa jak wcześniej.

**Start bazowy** („bez planu”) to to, co dom robi bez planu: pralka czy zmywarka startuje o godzinie,
o której zwykle jest włączana (mediana startów z historii, najbliższy dozwolony start; bez historii
początek przedziału). Start wcześniejszy niż przedział liczymy jako noc po dniu planu tylko wtedy, gdy
tam trafia do przedziału przez północ (zmywarka 19:00–07:00 włączana o 00:30); pralka z przedziałem
12:00–22:00 włączana zwykle o 09:00 startuje bez planu o 12:00. Auto ładuje pełną mocą od podłączenia, bojler trzyma termostat, a pompa grzeje
blokami z historii. `saving = cost_before − cost_after`, a procent na ekranie to oszczędność względem
kosztu bez planu tych samych urządzeń.

| Urządzenie | Akcja w planie |
|---|---|
| Z programem | Cały program w jednym z przedziałów (`allowed_starts`) |
| „Wykonaj po” | Łańcuch z poprzednikiem: start zaraz po jego końcu (przesuwają się razem), koniec przed `finish_by` i przed 06:00. Przerwa 0 min daje najwcześniejszy koniec, więc mieści się zawsze, gdy mieści się przerwa do 60 min |
| Ładowarka EV | Sesja `interruptible` w kwadransach przedziałów podłączenia; bez mocy w pliku 3,7 kW. Energia, która nie mieści się do 06:00, trafia do uwag („Zabraknie X kWh”) |
| Bojler | Magazyn ciepła z temperaturą wody (`water_heater.py`, niżej); układany poza rdzeniem, a jego grzanie obciąża dom w limicie przyłącza, zanim plan ułoży resztę |
| Pompa ciepła | Bloki grzania z dnia historii przeniesione na dzień planu, z energią dopasowaną do prognozowanej temperatury ([heat-pump.md](heat-pump.md)); każdy blok `shiftable` przesuwany najwyżej o `shift_hours` |

**Bojler** (`water_heater.py`): temperatura wody kwadrans po kwadransie w dobie planu (00:00–24:00).
Grzanie na poranek kolejnego dnia należy do planu na kolejny dzień, więc noc po dobie planu nie wchodzi
do kosztu bojlera.

- Kwadrans grzania to pełna moc grzałki (bez mocy w pliku 2 kW) i `+kWh / (litry × 1,163 Wh/(l·K))`.
- Pobór ciepłej wody na dobę: z historii bojlera w plikach (średnio z 7 ostatnich dni, bez akcji
  zastąpionych nowszym plikiem) minus straty termostatu przy 55°C, bo plik pokazuje zużycie bojlera
  z termostatem, czyli pobór i straty. Bez historii: liczba osób × 1,6 kWh. Pobór idzie po równo na
  każdą godzinę z `ready_times`, rozłożony na 2 h od tej godziny. Część poboru po północy (godzina
  gotowości po 22:00, np. 23:00 albo 00:00) należy do kolejnej doby i nie wchodzi do tej; woda i tak musi
  mieć 55°C na tę godzinę.
- Woda stygnie proporcjonalnie do różnicy z temperaturą pomieszczenia (22°C): przy 55°C ok. 0,5°C
  na godzinę, przy 75°C o ok. 60% szybciej. Grzanie na zapas kosztuje więc większe straty i plan
  wybiera je tylko wtedy, gdy różnica cen je pokrywa.
- Wymagania: co najmniej 55°C na godziny gotowości, poza nimi co najmniej 40°C, najwyżej 75°C,
  na końcu doby nie mniej niż na jej starcie (nikt nie pożycza ciepła z kolejnego dnia).
- **Bez planu** bojler to termostat: grzeje kwadrans, gdy woda ma mniej niż 55°C, więc o północy ma 55°C.
- **Z planem** w nocy wystarczy mniej: dobę zaczyna od 45°C (przy stygnięciu 0,5°C/h doczeka nad
  minimum 40°C do rana bez grzania o północy), a woda jest dogrzewana w tanich godzinach przed 06:00.
- **Plan**: programowanie dynamiczne po (kwadrans, temperatura); stany o tej samej temperaturze
  z dokładnością do 0,1°C łączymy (zostaje tańszy), a temperatury w wyniku liczy dokładna symulacja. Gdy grzałka nie nadąża,
  plan minimalizuje niedogrzanie, a `shortfall` i uwaga mówią, o ile woda będzie chłodniejsza.
- W odpowiedzi `water_heaters[]`: parametry i `temperatures` (na końcu każdego kwadransu: `before`, `after`).

**Co pracuje samo** (`day_background.py`, ZP-120): plan liczy dobę urządzeń spoza planu i zapisuje ją
w wyniku (`background`: przebiegi `runs` i urządzenia `devices` ze źródłem `forecast` albo `history`).
Symulacja wysyła do huba dokładnie to, więc plan i symulacja mają tę samą energię.

| Urządzenie | Doba w planie i symulacji |
|---|---|
| PV | Prognoza produkcji (ZP-118) na dobę planu; dla doby minionej pogoda z archiwum. Kilka falowników dzieli ją według produkcji w dniu referencyjnym. Bez pogody, bez paneli w profilu albo bez profilu: dzień referencyjny i uwaga dlaczego |
| Pompa ciepła spoza planu | Przebiegi dnia referencyjnego przeskalowane do temperatury doby planu (ZP-119), w mocy pompy; nadwyżka ponad dzień referencyjny wchodzi do zapasu w limicie przyłącza |
| Bojler spoza planu | Dzień referencyjny (zależy od zwyczajów, nie od pogody) |

**Nadwyżka PV** (`pv_balance.py`, `prosumer.py`, ZP-121). Gdy plan ma prognozę PV, koszt urządzeń to zmiana
rachunku domu w godzinach, a nie cena kwadransu razy energia. Operator bilansuje pobór i oddanie w każdej
godzinie, więc w godzinie:

- zużycie C to reszta domu i urządzenia z planu, a produkcja P to prognoza PV;
- gdy C > P, dom płaci ceny kwadransów za część zużycia, której nie pokryły panele: (C − P) / C × Σ zużycie × cena;
- gdy C ≤ P, dom nic nie pobiera, a oddaje P − C po wartości oddania.

Bez produkcji to dokładnie energia × cena, więc plan domu bez paneli się nie zmienia. Urządzenie w godzinie
z nadwyżką kosztuje tyle, ile dom traci na oddaniu, więc plan przesuwa je pod słońce także w G11. Gdy oddanie jest
warte więcej niż prąd z sieci (wysoka RCE), plan unika nadwyżki.

| Składnik | Skąd |
|---|---|
| Reszta domu | `house_load.rest_of_home`: o każdej porze większa z dwóch średnich z 7 ostatnich dni. Pierwsza to urządzenia stałe z plików urządzeń, a druga to zużycie domu z licznika (pobór − oddanie + produkcja PV z modelu, jak na ekranie „Fotowoltaika”) minus urządzenia elastyczne z plików urządzeń. Plik urządzeń z kompletem urządzeń daje to samo co licznik, a plik z samą pralką i autem uzupełnia licznik (`pv.rest_source = meter` i uwaga w planie). Do tego pompa i bojler spoza planu z `background` oraz bojler i pompa z planu. Zapas w limicie przyłącza dalej bierze maksimum urządzeń stałych |
| Produkcja | Migawka prognozy z `background.pv_forecast` (także bez falownika w pliku, gdy profil ma panele) pomniejszona o średni błąd prognozy: MAPE z kalibracji, a bez niej 20% (najwyżej 50%) |
| Cena zakupu | Ceny kwadransów taryfy, jak dotąd |
| Wartość oddania | `ExportValuation`, wspólne z ekranem „Fotowoltaika”: net-billing RCE (albo RCEm) × 1,23 ze średniej 4 kwadransów godziny, ujemna cena = 0, bez cen na ten dzień średnia RCE z tych samych godzin z 14 dni (szacunek), RCEm przed publikacją wyceniana po RCE; net-metering opust × cena zakupu. Bez żadnych cen oddanie nic nie jest warte (z uwagą) |

Harmonogram (`schedule(..., balance)`) wybiera miejsce grupy po zmianie rachunku przy już ułożonych akcjach,
a ładowanie auta wypełnia kwadranse, w których kWh najmniej podnosi rachunek. Bojler i pompę ciepła (planer
temperatury w domu i ciepła woda z pompy) plan układa przed resztą, z ceną kwadransów obniżoną do wartości oddania
w godzinach, w których nadwyżka reszty domu pokryje grzałkę albo pompę na najniższym poziomie mocy
(`effective_prices`).
Na koniec koszt każdej pozycji to zmiana rachunku godzin bez planu i według planu (`allocate`): zmiana w godzinie
dzieli się między urządzenia według zużycia × ceny kwadransu, więc pozycje sumują się do kosztu planu.

W odpowiedzi planu `pv`: prognoza (`forecast_kwh`), na ile plan liczy (`planned_kwh`, `uncertainty`, `uncertainty_source`),
skąd pogoda (`basis`, `weather_fetched_at`), wycena oddania (`export_estimated`, `export_unpriced`) i bilans paneli
bez planu i według planu (`before`, `after`: `self_kwh`, `export_kwh`, `import_kwh`, `plan_from_pv_kwh`, `export_pln`).
W planie jest też `balance` (reszta domu, produkcja i wartość oddania). Raport z symulacji (ZP-114) bierze koszty
pozycji z planu, a zmierzone zużycie urządzeń z planu wycenia tym samym rachunkiem. Bez prognozy PV (brak pogody)
plan liczy się bez paneli i mówi o tym w uwagach.

Przy taryfie ze stałą ceną i nadwyżce z paneli ekran planu nie mówi już, że przesuwanie nic nie da: plan przesuwa
urządzenia pod słońce.

### Plan idealny dnia z przeszłości (ZP-152)

Na ekranie „Plan na jutro” przełącznik „Jutro / Wybrany dzień” otwiera plan dnia z przeszłości, np. 14 maja,
do prezentacji i sprawdzania planera. Plan idealny układamy z pełną wiedzą o dobie, z tych samych ustawień
urządzeń co plan na jutro. Różnice:

| | Plan na jutro | Plan idealny (`kind = past_day`) |
|---|---|---|
| Pogoda | Prognoza | Archiwum (`weather.past`), czyli to, co naprawdę było |
| Produkcja PV | Prognoza pomniejszona o jej średni błąd (MAPE, bez kalibracji 20%) | Cała produkcja z archiwum (`uncertainty = 0`, `uncertainty_source = archive`). Do huba idzie ta sama energia |
| Bez planu (dzień z plików, `day_source = files`) | Zwykła godzina z historii | Pralka, zmywarka i auto o godzinie z pliku z tego dnia (auto z energią z pliku); urządzenia, które tego dnia nie pracowały, wypadają z planu z uwagą. Pompa ciepła i bojler jak zwykle (model i termostat) |
| Bez planu (dzień spoza plików, `day_source = settings`) | — | Jak plan na jutro: urządzenia i godziny z ustawień i historii, z uwagą |
| Reszta domu i rezerwa przyłącza | 7 ostatnich dni w plikach | Dzień z plików: zużycie z tej doby (`until` = koniec doby, 1 dzień); spoza plików jak plan na jutro |

Plan zapisuje się dla pary użytkownik + data, więc nie nadpisuje planu na jutro. Plan, który ułożono, zanim
plany miały `kind`, jest planem idealnym, gdy jego dzień jest wcześniejszy niż dzień ułożenia. Dzień bez cen
dla taryfy użytkownika daje `422` z komunikatem (także przy cenie dynamicznej, bo publikacja PSE nic tu nie
zmieni), a kalendarz zaczyna się od pierwszego dnia z cenami. Plan demo (brak cen na jutro), który wypada na
dzień z przeszłości, jest planem idealnym i ekran otwiera go w widoku „Wybrany dzień”.

Uruchomiony plan idealny ustawia zegar huba na północ swojej doby, jak każdy plan (ZP-113). Przebieg zapisuje
`plan_kind` w migawce, więc historia przebiegów i pasek przebiegu mówią „Plan idealny, 14 maja”.

### Pogoda i panele na ekranie planu (ZP-122)

Plan pokazuje, skąd wie o słońcu, z tego, co zapisał w chwili układania, a nie z bieżącej prognozy:

- `weather`: pogoda doby planu dla komórki domu (temperatura i zachmurzenie co kwadrans, `fetched_at`,
  `approximate_location`, `past` dla planu na miniony dzień z archiwum). Migawka jest w `background.weather`
  i powstaje także bez paneli (wtedy `WeatherService.day` bez płaszczyzn paneli). Bez lokalizacji albo pogody
  `weather = null`.
- `pv.hours`: godziny z produkcją: prognoza (`forecast_kwh`), na ile plan liczy (`planned_kwh`), reszta domu
  (`rest_kwh`), nadwyżka nad resztą domu przed urządzeniami z planu (`surplus_kwh`), urządzenia z planu (`plan_kwh`)
  i oddanie według planu (`export_kwh`). Suma `export_kwh` to `pv.after.export_kwh`. Liczy to
  `HouseBalance.hours`, tym samym rachunkiem godzinowym co koszty.
- `items[].pv_kwh`: ile prądu z paneli bierze pozycja według planu (`HouseBalance.from_pv`: w godzinie panele dzielą
  się po równo na każdą kWh zużycia, jak `plan_from_pv_kwh`, więc pozycje sumują się do niego).
- `pv_reason`: dlaczego plan liczy się bez paneli (`no_installation`, `no_weather`, `no_profile`, `no_forecast`).
- `pv.estimated_installation`: panele w profilu są szacunkowe.
- `pv.export_beats_grid`: w godzinach ze słońcem oddanie jest warte więcej niż prąd z sieci (np. RCE ok.
  1000 zł/MWh × 1,23 przy taryfie 0,63 zł/kWh w weekend). Plan wtedy nie przesuwa urządzeń pod słońce, a karta
  i uwaga planu to tłumaczą, bo inaczej wygląda to na błąd.

Na osi doby planu, pod cenami: pas zachmurzenia co godzinę (od błękitu do szarości, opis w dymku) z temperaturą
co 3 godziny (na telefonie co 6), a pod nim słupki prądu z paneli, na który plan liczy. Godziny z nadwyżką nad resztą
domu (co najmniej 0,05 kWh) są podświetlone na pasie paneli i pod urządzeniami, z legendą „nadwyżka z paneli”.
W tabeli przy pozycji, która bierze z paneli co najmniej 0,05 kWh, jest np. „1,2 z 1,4 kWh z paneli”. Plan bez
prognozy mówi to w pasie paneli (brak pogody, brak profilu), a dom bez paneli nie ma tego pasa. Karta „Prąd
z paneli” mówi, kiedy pobrano prognozę pogody, a przy panelach szacunkowych i lokalizacji przybliżonej ma dopisek
z linkiem do profilu.

Plany ułożone przed ZP-122 nie mają tych pól: oś pokazuje wtedy same ceny.

Uproszczenia, o których trzeba pamiętać:

- **Depozyt jak gotówka.** Oddanie wyceniamy tak samo jak Analiza taryf i ekran „Fotowoltaika” (te same ceny RCE/RCEm
  × 1,23 i opust, `ExportValuation`), ale w planie doby liczymy je od razu w złotówkach. Analiza taryf rozlicza depozyt
  w okresach: pokrywa on tylko część rachunku za energię (bez dystrybucji), wygasa po 12 miesiącach, a nadwyżki
  wraca 20–30%. To zależy od całego okresu rozliczeniowego, a nie od tego, o której godzinie jutro pracuje pralka,
  więc w planie wartość oddania jest górną granicą. Różnica nie zmienia kierunku decyzji, gdy prąd z sieci jest dużo
  droższy od RCE (typowo w słoneczne południe), ale przy wysokiej RCE plan może za bardzo unikać nadwyżki.
- **Plan i symulacja mają inną produkcję.** Plan liczy na prognozę pomniejszoną o jej średni błąd, a do huba idzie
  pełna prognoza (ZP-120). Raport z symulacji pokaże więc w części PV większą produkcję niż karta planu. Koszty
  urządzeń z planu raport liczy na migawce z planu, więc oszczędność zostaje porównywalna.
- **Panele szacunkowe.** Bez parametrów paneli w profilu („Nie znam parametrów”) prognoza liczy typową instalację,
  więc nadwyżka w planie jest orientacyjna; plan o tym pisze w uwagach.

**Historia pompy ciepła** (`plan_history.py`): ostatni dzień w plikach przed dniem planu, bo ogrzewanie
zależy od pogody, a wczoraj jest bliżej jutra niż ten sam dzień tygodnia sprzed tygodnia. Z tego dnia
są godziny grzania; ilość energii zmienia się o różnicę zużycia przy temperaturze dnia planu i dnia historii
(ZP-119, [heat-pump.md](heat-pump.md)). Bez pogody energia zostaje jak w dniu historii.

**Ceny** z taryfy profilu (`SchedulePriceService`). Brak ceny w którymkolwiek kwadransie dnia planu:
przy cenie dynamicznej `409` z `detail = {code: "no_prices", message, latest_price_date}` (PSE publikuje
ceny na kolejny dzień ok. 14:00, synchronizacja do 15:00), przy innej taryfie `422`. Ekran proponuje
wtedy plan demo na `latest_price_date`. Kwadranse po północy bez cen (taryfa dynamiczna) dostają cenę
z tej samej godziny dnia planu; `approximate_from` wskazuje pierwszy taki kwadrans, a uwaga mówi, że
koszt tej części jest przybliżony.

**Limit przyłącza** (moc umowna z profilu): urządzeń stałych plan nie przesuwa, ale zostawia na nie
miejsce. Dla każdej pory dnia (kwadransu zegarowego) bierzemy największy pobór urządzeń stałych
z ostatnich 7 dni w plikach (`device_slot_usage`, bez PV i bez kwadransów zastąpionych nowszym plikiem)
i dodajemy go jako obciążenie `load_only`. Maksimum zamiast średniej, żeby limit wystarczył także
w gorszy dzień; w nocy rezerwa jest mała, więc auto może ładować się prawie pełną mocą. Uwaga planu
podaje szczyt rezerwy i jego godzinę. Bez historii urządzeń stałych limit dotyczy tylko planowanych.
Odznaczona pompa ciepła albo bojler wchodzą do rezerwy tak jak urządzenia stałe: plan ich nie układa,
ale pracują same na termostacie. Odznaczona pralka, zmywarka czy auto jutro nie pracują, więc nie.
Bojler układamy poza rdzeniem, więc sam pilnuje limitu, a limit jest dla niego miękki. Kolejność
ważności: ciepła woda, potem limit, potem cena. Kwadrans, w którym pełna moc grzałki nie mieści się
obok rezerwy (i wcześniej ułożonego bojlera), nie jest zakazany, tylko obciążony karą (`OVER_LIMIT_PENALTY`,
dużo większą niż cena prądu, dużo mniejszą niż kara za zimną wodę). Plan omija więc takie kwadranse,
kiedy może, a grzeje w nich tylko wtedy, gdy inaczej woda byłaby za zimna; ostrzeżenie podaje wtedy
godziny („grzeje o 17:00–17:30 mimo ryzyka przekroczenia mocy przyłącza…”). Rezerwa to maksimum z 7 dni,
więc przekroczenie jest możliwe, ale nie pewne; bez planu termostat i tak grzałby bez względu na limit.
Termostat „bez planu” zostaje bez zmian, bo opisuje to, co dom robi dziś.

**Poza planem**: produkcja PV (brak prognozy), a urządzenia stałe tylko jako rezerwa w limicie, więc
oszczędność dotyczy tylko planowanych urządzeń. Plan nie wysyła jeszcze komend do huba.

**Temperatura wody o północy** to założenie (termostat 55°C, plan 45°C): obie wersje kończą dobę
z co najmniej taką temperaturą, z jaką ją zaczęły, więc każdy dzień wygląda tak samo. Pomiar przyjdzie z huba.

Odpowiedź ma `notes` (jak ułożyliśmy plan) i osobno `warnings`: co nie wyjdzie tak, jak chciał użytkownik
(auto nie naładuje się do końca, bojler nie nadąży, program nie mieści się w godzinach, brak historii).
Ustawienia (`GET /preferences`) mają `flat_tariff`: taryfa G11 bez ceny dynamicznej, przy której przesuwanie
prawie nic nie daje; ekran podpowiada wtedy Analizę taryf. Bloki pompy ciepła są opisane porą dnia
(„grzanie rano”, „po południu”…).

Ekran: „Plan na jutro” ma przycisk „Zapisz i ułóż plan”, po którym pokazuje plan (koszt bez planu,
według planu i oszczędność z procentem, ostrzeżenia, tabela przydziałów, konflikty, przyciski, oś doby
i nocy do 6:00 na tle cen, uwagi; temperatura wody w bojlerze w okienku po kliknięciu „Temperatura wody”).
Plan na dzień wcześniejszy niż jutro ma pasek z przyciskiem „Ułóż plan na jutro”
z przyciskami „Zatwierdź plan” i „Edytuj ustawienia”. Plan ułożony po ostatnim zapisie ustawień
pokazuje się od razu po wejściu na stronę.

Bojler w plikach testowych: `generate_devices_file.py --with-water-heater` (domyślne pliki demo go nie mają).

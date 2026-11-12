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

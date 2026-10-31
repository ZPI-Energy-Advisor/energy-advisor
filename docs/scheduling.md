# Harmonogramowanie akcji urządzeń

`backend/app/services/scheduling.py` rozmieszcza akcje urządzeń tak, żeby koszt przy cenach
kwadransów był najmniejszy. To czysta funkcja, bez bazy i bez wiedzy o taryfach. Ta sama służy do
poprawy historycznego okresu i do planu na przyszłość: różni je tylko to, skąd pochodzą akcje i ceny.

```python
schedule(actions, prices, max_grid_kw=None) -> ScheduleResult
```

- `actions`: lista `ScheduleAction`; z pliku urządzeń buduje ją `actions_from_devices`.
- `prices`: słownik początek kwadransa (UTC) → cena za kWh. Dziś ceny taryfy dynamicznej.
- `max_grid_kw`: limit przyłącza; `None` go wyłącza.

Na razie obsługiwane są tryby `fixed` i `shiftable`. `interruptible` (EV) zostaje jako `fixed`.
Produkcja PV nie trafia na wejście, bo w wycenie nie pomniejsza zużycia.

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
Korzysta z niego zakładka „Optymalizacja”: dla każdej doby pokazuje ceny oraz akcje urządzeń przed i po.

## Założenia

- Wynik dla historii zakłada, że z góry wiadomo, jakie akcje będą danego dnia. Ceny na dany dzień są
  znane z wyprzedzeniem, bo PSE publikuje je dzień wcześniej.
- Czas jest liczony w UTC, a okna i doby w czasie lokalnym (`Europe/Warsaw`).

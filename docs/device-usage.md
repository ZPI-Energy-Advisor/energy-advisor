# Zużycie i koszt per urządzenie

Dane do wykresów na Dashboardzie w podziale na kategorie, typy albo pojedyncze urządzenia
(ZP-81, wykres w ZP-82).

## Scalanie plików urządzeń

Każdy wgrany plik zostawia w `device_actions` i `device_slot_usage` swoje wiersze, także gdy
nowszy plik opisuje te same urządzenia w tym samym czasie. Obowiązuje zasada z ZP-79:

> Kwadrans urządzenia należy do najnowszego pliku (kolejność uploadu), który zawiera to urządzenie
> i obejmuje ten kwadrans swoim okresem.

Wynik scalania jest zapisany w bazie:

- `energy_data_files.period_start` / `period_end` (timestamptz): dokładny okres pliku, z pola
  `period` pliku urządzeń albo od pierwszego do końca ostatniego kwadransu pliku licznika;
- `device_slot_usage.superseded`: `true`, gdy nowszy plik przykrywa ten kwadrans urządzenia.
  Wiersze nie są usuwane, więc usunięcie nowszego pliku przywraca starsze (flagi wracają na
  `false`).

Flagi są przeliczane w transakcji uploadu i usuwania pliku, tylko dla urządzeń tego pliku w jego
okresie. Upload jedynie oznacza wiersze starszych plików jako przykryte; usunięcie liczy przedziały
przykrycia dla par (plik, urządzenie) i zmienia tylko wiersze, których flaga się zmienia. Akcja
obowiązuje, gdy obowiązuje jej pierwszy kwadrans.

„Wszystkie pliki urządzeń” (`/energy-files/all-devices/data`) sumują wiersze z
`NOT superseded`. Jak przy imporcie pojedynczego pliku, w każdym kwadransie produkcja PV najpierw
pokrywa zużycie: pobór = max(0, suma energii urządzeń).

## API

```
GET /api/v1/energy-files/{file_id | all-devices}/devices/usage
```

| Parametr | Domyślnie | Znaczenie |
|---|---|---|
| `group_by` | `category` | `category`, `type` albo `instance` (pojedyncze urządzenie) |
| `resolution` | `1h` | `15m`, `1h` albo `1d`; okresy w czasie lokalnym Europe/Warsaw, doba zmiany czasu ma 23 albo 25 godzin |
| `from`, `to` | okres danych | zakres dni lokalnych (RRRR-MM-DD), oba włącznie |
| `tariff` | taryfa z profilu | taryfa kosztów (np. `G12`); bez taryfy w profilu albo bez jej cennika: G11 z informacją w `tariff.note` |
| `category`, `type` | – | tylko urządzenia z tej kategorii albo tego typu (drill-down) |
| `meter` | – | `all` albo id pliku licznika: dodaje grupę „Reszta domu” |

Koszt kwadransu to jego zużycie razy cena tego kwadransu w wybranej taryfie z cennika zapisanego
przy imporcie (`slot_prices`), tak jak koszt na Dashboardzie. Dla pojedynczego pliku liczą się
wszystkie jego wiersze; dla `all-devices` tylko obowiązujące.

Odpowiedź:

- `periods`: początki okresów z przesunięciem względem UTC;
- `groups`: dla każdej grupy `kwh` i `cost_pln` w okresach, sumy oraz metadane (`category`,
  `device_type`, `device_type_label`, `device_id`, `device_name`, `devices_count`); posortowane
  od największego zużycia;
- `production`: produkcja PV jako wartości dodatnie, poza grupami (zużycie grup − produkcja =
  pobór − oddanie w każdym kwadransie);
- `rest_of_house` (z `meter`): licznik − urządzenia w dniach wspólnych obu źródeł, liczone jako
  saldo z siecią (licznik: pobór − oddanie, urządzenia: zużycie − produkcja). Kwadrans, w którym
  urządzenia przekraczają licznik, ma resztę 0, a dzień, w którym przekraczają go o więcej niż 1%
  (min. 0,05 kWh), trafia do `exceeded_days`;
- `missing_price_slots`: kwadranse zużycia bez ceny w taryfie (np. brak cen dynamicznych).

Błędy: plik licznika albo brak plików urządzeń – 409, cudzy albo nieistniejący plik – 404, brak
tokenu – 401, zła taryfa, rozdzielczość albo zakres – 422.

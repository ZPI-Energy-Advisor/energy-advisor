# Cennik w plikach: format danych, model w bazie, cena maksymalna i oferty dynamiczne

Stawki taryfowe (ZP-99) trzymamy jako pliki JSON w repozytorium i ładujemy do bazy skryptem
`backend/scripts/load_tariffs.py`. Każda liczba ma źródło (dokument i stronę) i okres ważności. Ten dokument
opisuje format plików, reguły walidacji, model w bazie oraz sposób liczenia ceny maksymalnej, akcyzy i ofert
z ceną dynamiczną.

## Pliki

```
backend/data/tariffs/<rok>/<operator>.json   # pge, tauron, enea, energa, stoen
backend/data/tariffs/<rok>/regulatory.json   # opłaty ogólnokrajowe: jakościowa, OZE, kogeneracyjna,
                                             # mocowa, przejściowa, akcyza, VAT
```

Dane zaczynają się 24.08.2024 (od tego dnia mamy RCE i oferty z ceną dynamiczną), więc pliki 2024 obejmują
24.08–31.12.2024. Dane testowe (zmyślone) są wyłącznie w `backend/tests/fixtures/tariffs/`.

Każdy plik ma pole `covers` — zakres dat, za który odpowiada. Wszystkie wpisy pliku muszą mieścić się w tym
zakresie. Wpis obowiązujący dłużej (np. taryfa sprzedawcy 1.07.2024–30.09.2025) zapisujemy w każdym roku
osobno, przycięty do zakresu pliku, z tym samym dokumentem źródłowym.

## Konwencje

- Kwoty i stawki jako napisy dziesiętne z kropką: `"0.3469"` (zł/kWh netto), `"5.50"` (zł/mies. netto). Bez
  VAT. Stawki dynamiczne rynku w zł/MWh (`market_price_floor`, `market_price_cap`).
- Daty `RRRR-MM-DD`, oba końce włącznie.
- Strefy numerujemy od `"1"`: strefa 1 to dzienna/szczytowa (droższa), dalej kolejne strefy w kolejności
  z taryfy (np. G13: 1 przedpołudniowa, 2 popołudniowa, 3 pozaszczytowa). Te same numery stref w części
  dystrybucyjnej i energetycznej.
- Godziny w czasie lokalnym licznika jako `"HH:MM"`, koniec przedziału wyłącznie, `"24:00"` = koniec doby.
- Strona dokumentu: numer strony taryfy, a w nawiasie strona PDF, np. `"s. 61 (PDF 63)"`; dla aktów prawnych
  jednostka redakcyjna, np. `"art. 3 ust. 1 pkt 1 lit. c"`.

### Źródło

Każda grupa wartości ma obiekt źródła:

```json
{"doc": "osd-2025", "page": "s. 61 (PDF 63)"}
```

`doc` to klucz z sekcji `documents` pliku. Gdy wartości nie da się odczytać wprost z dokumentu, źródłem jest
opis, skąd ją przyjęto (`doc`/`page` opcjonalnie wskazują podstawę):

```json
{"text": "godziny jak w taryfie 2026, bo taryfa 2025 zostawia je operatorowi", "doc": "osd-2026", "page": "s. 11 (PDF 13)"}
```

### Dokumenty

```json
"documents": {
  "osd-2025": {
    "title": "Taryfa dla usług dystrybucji energii elektrycznej PGE Dystrybucja S.A. na rok 2025, decyzja Prezesa URE DRE.WRE.4211.44.7.2024.AKr3 z 16.12.2024 (BB URE Nr 274 (4518))",
    "url": "https://bip.ure.gov.pl/download/3/19080/PGEDystrybucja.pdf"
  }
}
```


## Plik operatora

```json
{
  "operator": "PGE",
  "year": 2025,
  "covers": {"from": "2025-01-01", "to": "2025-12-31"},
  "documents": { ... },
  "distribution": [ ... ],
  "energy": [ ... ],
  "dynamic_offers": [ ... ],
  "unsupported": [ ... ],
  "notes": ["dowolne uwagi do przeglądu, po polsku"]
}
```

### `distribution` — taryfa OSD

Wpis = okres, w którym stawki dystrybucyjne się nie zmieniają (nowa taryfa, zmiana taryfy, zniesienie
abonamentu od 1.10.2026 itd.).

```json
{
  "valid_from": "2025-01-01",
  "valid_to": "2025-12-31",
  "subscription": {"1": "4.50", "2": "2.25", "6": "0.75"},
  "subscription_source": {"doc": "osd-2025", "page": "s. 61 (PDF 63)"},
  "tariffs": {
    "G12": {
      "zones": {
        "1": {"name": "dzienna", "rate": "0.4015"},
        "2": {"name": "nocna", "rate": "0.0765"}
      },
      "fixed_monthly": {"1f": "8.50", "3f": "14.40"},
      "rates_source": {"doc": "osd-2025", "page": "s. 61 (PDF 63)"},
      "hours": [
        {"zone": "1", "days": "all", "season": ["04-01", "09-30"], "intervals": [["06:00", "15:00"], ["17:00", "22:00"]]},
        {"zone": "2", "days": "all", "season": ["04-01", "09-30"], "intervals": [["00:00", "06:00"], ["15:00", "17:00"], ["22:00", "24:00"]]},
        {"zone": "1", "days": "all", "season": ["10-01", "03-31"], "intervals": [["06:00", "13:00"], ["15:00", "22:00"]]},
        {"zone": "2", "days": "all", "season": ["10-01", "03-31"], "intervals": [["00:00", "06:00"], ["13:00", "15:00"], ["22:00", "24:00"]]}
      ],
      "hours_source": {"doc": "osd-2025", "page": "s. 15 (PDF 17)"}
    }
  }
}
```

- `subscription` — opłata abonamentowa zł/mies. dla okresów rozliczeniowych oferowanych w grupach G (klucze
  `1`, `2`, `6`, `12`). Klucze wyznaczają, jakie okresy rozliczeniowe liczymy u operatora. Od dnia, w którym
  abonament zniesiono, wpis ma te same klucze z wartością `"0.00"`. Taryfa może mieć własne `subscription`
  (nadpisuje wspólne).
- `fixed_monthly` — składnik stały stawki sieciowej, `1f` (jednofazowy) i `3f` (trójfazowy).
- `hours` — reguły godzin stref. `days`: `"all"` albo lista z `workday` (pon.–pt.), `saturday`,
  `sunday_holiday` (niedziele i dni ustawowo wolne od pracy; święto w sobotę też jest tu). `season`: `"all"`
  albo `["MM-DD", "MM-DD"]` (oba końce włącznie, zakres może przechodzić przez Nowy Rok, np.
  `["10-01", "03-31"]`). Reguły jednej taryfy muszą dla każdego rodzaju dnia i każdego dnia roku pokryć dobę
  bez dziur i nakładania.

### `energy` — taryfa sprzedawcy z urzędu

```json
{
  "valid_from": "2025-01-01",
  "valid_to": "2025-09-30",
  "seller": "PGE Obrót S.A.",
  "prices_include_excise": false,
  "excise_source": {"doc": "obrot-2024", "page": "pkt 1.6, s. 3 (PDF 5)"},
  "price_cap": "0.5000",
  "price_cap_source": {"doc": "ustawa-2022-2243", "page": "art. 2 pkt 1 lit. a, art. 3 ust. 1 pkt 1 lit. d"},
  "trade_fee_monthly": "0.00",
  "trade_fee_source": {"doc": "obrot-2024", "page": "..."},
  "source": {"doc": "obrot-2024-07", "page": "s. 3 (PDF 5)"},
  "tariffs": {
    "G11": {"zones": {"1": "0.6288"}},
    "G12": {"zones": {"1": "0.7108", "2": "0.4451"}}
  }
}
```

- `zones` — cena energii czynnej zł/kWh netto dla każdej strefy (te same numery co w dystrybucji).
- `prices_include_excise` — czy ceny z dokumentu zawierają akcyzę. Taryfy URE sprzedawców podają ceny bez
  akcyzy (`false`); E.ON podaje ceny netto z akcyzą (`true`). Akcyzę dolicza silnik osobną pozycją ze stawki
  w `regulatory.json`; przy `true` odejmuje ją najpierw od ceny.
- `price_cap` — cena maksymalna zł/kWh netto bez akcyzy (ustawa z 27.10.2022, Dz.U. 2024 poz. 1622, art. 2 pkt 1:
  „cena ta nie zawiera podatku od towarów i usług oraz podatku akcyzowego”). Silnik liczy energię strefy po
  `min(cena bez akcyzy, price_cap)` i dolicza akcyzę. Wpisy 24.08.2024–31.12.2025 mają `"0.5000"`; ofert
  dynamicznych to nie dotyczy.
- `trade_fee_monthly` — opłata handlowa zł/mies. netto, jedna kwota niezależnie od okresu rozliczeniowego
  (brak pola = 0). Gdy obowiązuje cena
  maksymalna, jest ona jedyną składową opłat w obrocie (art. 3 ust. 8 tej ustawy) — wtedy wpis ma opłatę 0.
- Każda taryfa z części dystrybucyjnej musi mieć ceny energii w tych samych dniach i odwrotnie (zgodność
  sprawdzana per taryfa).

### `dynamic_offers` — oferty z ceną dynamiczną

```json
{
  "valid_from": "2026-07-01",
  "valid_to": "2026-12-31",
  "seller": "PGE Obrót S.A.",
  "name": "Dynamiczna energia z PGE",
  "distribution_tariffs": ["G11", "G12", "G12w", "G12n"],
  "billing_cycle_months": 1,
  "margin": "0.0855",
  "prosumer_margin": "0.1150",
  "trade_fee_monthly": "22.00",
  "prosumer_trade_fee_monthly": "27.00",
  "market_price_floor": "0",
  "market_price_cap": "1999",
  "prices_include_excise": false,
  "source": {"doc": "pge-dyn-2026-2", "page": "Załącznik nr 2, s. 1"},
  "field_sources": {"trade_fee_monthly": {"doc": "pge-dyn-2026-2-zal5", "page": "s. 2"}}
}
```

Cena kwadransa = `clamp(cena giełdowa, market_price_floor, market_price_cap) / 1000 + marża` (zł/kWh netto),
marża prosumenta (`prosumer_margin`), gdy profil ma instalację PV. Brak `market_price_floor` = ceny ujemne
dozwolone; brak `market_price_cap` = bez górnego limitu. Cenę giełdową bierzemy z RCE (PSE), także gdy oferta
odwołuje się do fixingu I TGE — to przybliżenie (dla PGE 2.03.2026 różnice godzinowe do ok. 0,05 zł/kWh, średnio
+0,4% / +1,3%). `prices_include_excise` mówi, czy marża zawiera akcyzę (np. Energa: WK zawiera akcyzę).
Opłata handlowa jest miesięczna, okres rozliczeniowy oferty (`billing_cycle_months`, zwykle 1) liczymy
niezależnie od okresu z profilu. `distribution_tariffs` to grupy, z którymi sprzedawca dopuszcza ofertę: dla każdej
liczymy osobny rachunek z dystrybucją, strefami i abonamentem tej grupy (klient zostaje przy swojej grupie, zmienia
tylko umowę na energię). Ofert dynamicznych nie
obejmuje cena maksymalna. Oferta przed datą wprowadzenia nie istnieje — plik z wcześniejszymi dniami dostaje
krótką informację „oferta dostępna od …”.

### `unsupported` — taryfy jeszcze nieliczone

```json
{
  "code": "G12as",
  "name": "Taryfa antysmogowa",
  "valid_from": "2025-01-01",
  "valid_to": "2025-12-31",
  "reason": "Tańsza stawka nocna dotyczy tylko zużycia ponad zużycie z tego samego okresu roku poprzedniego, a tej wielkości nie ma w pliku z odczytami.",
  "source": {"doc": "osd-2025", "page": "pkt 3.1.29–3.1.32, s. 27 (PDF 29)"}
}
```

Grupy G oferowane przez operatora, których nie liczymy (strefy ogłaszane przez operatora lub zmieniane co
miesiąc, stawki zależne od historii zużycia, brak ceny energii w taryfie sprzedawcy z urzędu, liczniki
przedpłatowe itd.). Wyniki kalkulacji pokazują je jedną linijką pod tabelą porównania, powód w podpowiedzi.

## Plik `regulatory.json`

```json
{
  "year": 2025,
  "covers": {"from": "2025-01-01", "to": "2025-12-31"},
  "documents": { ... },
  "periods": [
    {
      "valid_from": "2025-07-01",
      "valid_to": "2025-12-31",
      "quality_fee_per_kwh": {"value": "0.0321", "source": {...}},
      "renewable_fee_per_kwh": {"value": "0.0035", "source": {...}},
      "cogeneration_fee_per_kwh": {"value": "0.0030", "source": {...}},
      "excise_per_kwh": {"value": "0.0050", "source": {...}},
      "vat_rate": {"value": "0.23", "source": {...}},
      "capacity_fee_monthly": {
        "bands": [
          {"min_kwh": "0", "max_kwh": "500", "fee": "2.86"},
          {"min_kwh": "500", "max_kwh": "1200", "fee": "6.86"},
          {"min_kwh": "1200", "max_kwh": "2800", "fee": "11.44"},
          {"min_kwh": "2800", "max_kwh": null, "fee": "16.01"}
        ],
        "source": {...}
      },
      "transition_fee_monthly": {
        "bands": [
          {"min_kwh": "0", "max_kwh": "500", "fee": "0.02"},
          {"min_kwh": "500", "max_kwh": "1200", "fee": "0.10"},
          {"min_kwh": "1200", "max_kwh": null, "fee": "0.33"}
        ],
        "source": {...}
      }
    }
  ]
}
```

Progi opłat mocowej i przejściowej dotyczą rocznego zużycia (pobór z pliku przeskalowany do 365 dni), dolna
granica włącznie, górna wyłącznie. Okresy nie mogą się nakładać i muszą pokrywać każdy dzień zakresu pliku.

**Opłata przejściowa jest ogólnokrajowa.** Stawki dla gospodarstw domowych ustala ustawa o rozwiązaniu KDT
(art. 11b ust. 1: 0,02 / 0,10 / 0,33 zł/mies.), a taryfy wszystkich pięciu OSD 2024–2025 powtarzają te same
kwoty; od 2026 r. jej nie ma (M.P. 2025 poz. 1211). Podobnie stawka jakościowa dla nN (z taryfy PSE), OZE,
kogeneracyjna i mocowa — dlatego są w jednym pliku na rok, a nie w plikach operatorów. Przy wprowadzaniu
danych sprawdzamy, że taryfa każdego OSD podaje te same wartości (rozbieżność = uwaga w przeglądzie).

## Walidacja przy ładowaniu

`load_tariffs.py` odrzuca plik z czytelnym błędem (plik, wpis, taryfa, dzień), gdy:

- brakuje pola, data lub kwota ma zły format, wpis wychodzi poza `covers`, źródło wskazuje nieznany dokument, źródło nie ma ani
  dokumentu ze stroną, ani opisu (`text`);
- strefa nie ma stawki dystrybucyjnej, ceny energii albo godzin, albo zbiory stref się różnią;
- godziny taryfy dla któregoś rodzaju dnia i dnia roku mają dziurę albo się nakładają (komunikat podaje taryfę,
  rodzaj dnia, dzień i godzinę);
- ta sama taryfa jest w dwóch nakładających się wpisach (dystrybucja, energia, oferty dynamiczne);
- dzień ma stawki dystrybucji taryfy, a nie ma cen energii (lub odwrotnie); oferta dynamiczna nie ma
  dystrybucji którejś z grup `distribution_tariffs`;
- okresy opłat regulacyjnych nakładają się albo nie pokrywają zakresu pliku.

Pełny zakres 24.08.2024–31.12.2026 (każdy dzień, każda liczona taryfa każdego operatora, opłaty regulacyjne)
sprawdza test `tests/test_tariff_data_files.py` na prawdziwych plikach.

## Ładowanie do bazy

```bash
docker compose exec backend python scripts/load_tariffs.py data/tariffs          # wszystkie pliki
docker compose exec backend python scripts/load_tariffs.py --check data/tariffs  # tylko walidacja
```

Wszystkie pliki w jednej transakcji. Plik zastępuje dane w swoim zakresie dat: usuwa definicje operatora
(okresy regulacyjne, taryfy nieliczone) leżące w całości w `covers` i wstawia nowe. Jeżeli w bazie jest wpis
leżący częściowo poza zakresem pliku, skrypt odmawia (nie usuwa danych spoza zakresu). Dwukrotne ładowanie daje
te same dane bez duplikatów.

Loader łączy wpisy pliku w definicje taryf: definicja = taryfa × część wspólna okresu wpisu dystrybucji i wpisu
energii (oferta dynamiczna × dystrybucja każdej z jej `distribution_tariffs`, z grupą w kolumnie
`distribution_group`). Definicja zapamiętuje osobno okres
i źródło części dystrybucyjnej i energetycznej.

## Model w bazie

| tabela | zawartość |
|---|---|
| `tariff_definitions` | operator, kod taryfy, nazwa, okres definicji; część OSD: `distribution_valid_from/to`, `distribution_source`, składnik stały 1f/3f; część sprzedawcy: `energy_valid_from/to`, `energy_source`, `energy_includes_excise`, `energy_price_cap_per_kwh`; oferta dynamiczna: `prosumer_margin_per_kwh`, `market_price_floor_mwh`, `market_price_cap_mwh`, `required_billing_cycle_months`; opłata handlowa: `trade_fee_monthly`, `prosumer_trade_fee_monthly`; grupa dystrybucyjna: `distribution_group` |
| `osd_variable_network_rates` | stawka zmienna strefy (+ nazwa strefy) |
| `supplier_ure_rates` | cena energii strefy; w ofercie dynamicznej strefa 1 = marża |
| `osd_subscription_fees` | abonament per okres rozliczeniowy |
| `tariff_zone_hours` | definicja, strefa, rodzaj dnia (`workday`/`saturday`/`sunday_holiday`), sezon (`MM-DD`–`MM-DD`), od–do w minutach doby |
| `unsupported_tariffs` | taryfy nieliczone: operator, kod, nazwa, powód, okres, źródło |
| `regulatory_periods` | jakościowa, OZE, kogeneracyjna, akcyza, VAT, `source` + progi mocowej i przejściowej |

## Strefy, święta i zegar licznika

Strefę kwadransa wyznacza `app/services/tariff_zones.py` z `tariff_zone_hours` definicji ważnej w dniu odczytu:
rodzaj dnia (dni ustawowo wolne od pracy liczone w kodzie: stałe daty, Wielkanoc i święta ruchome, Wigilia od
2025 r.), sezon i minuta doby. Tej samej funkcji używa silnik taryf i bilansowanie PV.

**Założenie o zegarze:** odczyty z plików mają czas lokalny (CET/CEST), więc godziny stref stosujemy do czasu
lokalnego. Taryfy OSD mówią, że liczniki strefowe chodzą według czasu zimowego, chyba że same przełączają czas;
liczniki zdalnego odczytu (AMI), z których pochodzą pliki 15-minutowe, przełączają czas automatycznie. Licznik
bez przełączania w lecie przesuwałby strefy o godzinę — tego nie modelujemy. Doba zmiany czasu: w 23-godzinnej
nie ma odczytów 02:00–03:00, w 25-godzinnej oba wystąpienia godziny 02:00–03:00 są zsumowane w jednym lokalnym
kwadransie (tak zapisuje je import) i trafiają do strefy tej godziny.

## Endpointy i skrypty

- `GET /api/v1/tariffs/catalog?operator=PGE&date=RRRR-MM-DD` — cennik operatora na dzień (taryfy, stawki
  stref, godziny, opłaty stałe, abonament, opłata handlowa, parametry oferty dynamicznej, opłaty regulacyjne,
  taryfy nieliczone) ze źródłami. Tylko do odczytu, dla Dashboardu.
- `GET /api/v1/tariffs/options?operator=PGE` — taryfy i okresy rozliczeniowe liczone u operatora oraz taryfy
  nieliczone (formularz profilu). Zapis profilu odrzuca (422) taryfę i okres spoza tej listy, jeśli operator ma
  w bazie jakikolwiek cennik.

# Lokalizacja domu i instalacja PV w profilu

Dane wejściowe do pogody i prognozy produkcji PV (ZP-116, ZP-148), używane przez worker pogody (ZP-117)
i prognozę PV (ZP-118).

## Lokalizacja (`base_info.location`)

Pogodę pobieramy dla punktu, więc profil potrzebuje współrzędnych. Siatka modeli pogody ma kilka kilometrów,
a worker zaokrągla współrzędne do ok. 0,1°, dlatego wystarcza dokładność obszaru kodu pocztowego. Mapy
w formularzu nie ma, bo dokładniejsze położenie domu nie zmienia prognozy.

Backend wyznacza współrzędne przy zapisie profilu, gdy zmieni się kod pocztowy lub miejscowość, a dla profili
zapisanych przed ZP-116 przy pierwszym odczycie. Geokoder to OpenStreetMap Nominatim: Open-Meteo Geocoding nie
zna polskich kodów pocztowych, a po samej nazwie miejscowości nie odróżni setek wsi o nazwie „Nowa Wieś”.

Zapis sprawdza, czy miejscowość pasuje do kodu pocztowego:

1. Nominatim szuka kodu pocztowego (środek jego obszaru).
2. Miejscowość o podanej nazwie musi leżeć w pobliżu tego obszaru (ok. ±30 km). Współrzędne to współrzędne tej
   miejscowości, a nazwa w profilu pochodzi z OpenStreetMap, np. „Wroclaw” → „Wrocław”.
3. Gdy miejscowości tam nie ma, zapis kończy się błędem 422 przy polu „Miejscowość”, np. „Miejscowość Wronki nie
   pasuje do kodu pocztowego 51-515. Ten kod to okolice: Wrocław.”
4. Gdy kodu nie ma w OpenStreetMap, miejscowość musi istnieć w regionie pocztowym kodu (pierwsza cyfra); inaczej
   błąd przy kodzie albo przy obu polach („Nie znaleźliśmy…”).

Formularz sprawdza adres od razu, bez zapisu profilu: po Enterze albo wyjściu z pola miejscowości lub kodu
wywołuje `GET /api/v1/users/me/profile/address-lookup?town=&postal_code=` i pokazuje znalezione miejsce.

- Sam kod pocztowy uzupełnia miejscowość: miasto albo siedzibę gminy z obszaru kodu.
- Sama miejscowość uzupełnia kod, gdy jest jednoznaczna i OpenStreetMap zna jej kod. Gdy oprócz miasta są wsie
  o tej nazwie, wybieramy miasto z dopiskiem o wsiach. Kilka wsi o tej nazwie: prośba o kod pocztowy.
- Oba pola: to samo sprawdzenie co przy zapisie; błąd trafia od razu pod pole.

Formularz pamięta zapisany stan profilu. Przy niezapisanych zmianach pokazuje „Masz niezapisane zmiany”,
pyta przed przejściem linkiem do innej zakładki albo wylogowaniem, a przeglądarka ostrzega przy zamknięciu
karty. Lokalizacja wyliczona z adresu nie liczy się jako zmiana (liczy się adres), a wskazana ręcznie tak.

Profilu z błędnym adresem nie da się zapisać. Starszy profil z takim adresem przy odczycie dostaje lokalizację
przybliżoną zamiast błędu, żeby dało się go otworzyć i poprawić.

| `source` | Skąd | Dokładność |
|---|---|---|
| `postal_code` | Miejscowość potwierdzona kodem pocztowym | kilka km |
| `town` | Kodu nie ma w OpenStreetMap: miejscowość o tej nazwie w regionie pocztowym, najbliższa jego głównemu miastu | zwykle kilka km; przy częstej nazwie może trafić sąsiednią wieś |
| `postal_region` | Geokoder nie odpowiedział albo starszy profil ma niepasujący adres: główne miasto regionu pocztowego (`approximate: true`) | nawet ok. 200 km; ponawiane przy kolejnym zapisie i odczycie profilu |
| `manual` | Położenie z przeglądarki („Użyj mojej lokalizacji”); adres i tak musi przejść sprawdzenie | zostaje do zmiany adresu albo „Wyznacz z kodu pocztowego” |

Klient może przysłać tylko lokalizację `manual`; inne źródła ustala backend. `location: null` w zapisie wraca
od lokalizacji `manual` do wyznaczonej z kodu. Pole `address` („50-370 Wrocław”) mówi, dla jakiego adresu
wyznaczono współrzędne.

Nominatim: najwyżej jedno zapytanie na sekundę, identyfikujący `User-Agent` (`GEOCODER_USER_AGENT`), wyniki
zapamiętane w procesie. Po błędzie sieci, odpowiedzi 403, 429 albo 5xx przez 5 minut nie pytamy Nominatim
i od razu bierzemy przybliżenie z regionu (bez sprawdzenia adresu), żeby zapis profilu nie czekał na kolejne
timeouty. Adres serwera można zmienić przez `NOMINATIM_URL`. Testy używają geokodera offline
(`tests/conftest.py`), więc nie wysyłają zapytań.

## Instalacja PV (`pv_config.installation`)

Wspólna dla net-billingu i net-meteringu. Panele opisują grupy (połacie dachu), bo produkcja zależy od kierunku
i nachylenia, np. 4 panele na południe i 3 na wschód.

| Pole | Opis |
|---|---|
| `arrays[]` | 1–4 grup: `power_kwp`, `azimuth` (0 = południe, −90 = wschód, 90 = zachód, jak w Open-Meteo), `tilt` (0–90°), opcjonalnie `panel_count` |
| `panel_power_w` | Moc jednego panelu (50–1000 W). Gdy jest podana, moc grupy = liczba paneli × moc panelu i `power_kwp` liczy backend |
| `inverter_power_kw` | Opcjonalna moc falownika: górny limit produkcji AC |
| `estimated` | Użytkownik nie zna parametrów: typowa instalacja 6 kWp na południe, 35°; prognoza jest orientacyjna |
| `total_kwp` | Suma mocy grup, najwyżej 50 kWp (mikroinstalacja) |

Net-metering liczy opust z `power_of_pv_kwp`, czyli `total_kwp` (0,8 do 10 kWp, 0,7 powyżej). Migracja
`a7d3e9c2b5f1` zamienia dawne `power_of_pv_kwp` na jedną grupę na południe z nachyleniem 35°, więc kwoty
rachunków się nie zmieniają. Profil net-billing sprzed ZP-148 nie ma paneli i dalej jest poprawny;
`pv_installation()` zwraca dla niego typową instalację z `estimated: true`.

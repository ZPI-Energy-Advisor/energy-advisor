# Wygląd i formaty we frontendzie

Wspólne zasady ekranów (ZP-125). Nowy ekran korzysta z tych funkcji i klas, a nie z własnych kopii.

## Formaty liczb i dat

Wszystkie są w `frontend/src/utils/format.js`. Brak wartości (`null`, `undefined`) to „—”.

| Co | Funkcja | Przykład |
|---|---|---|
| Kwota | `formatPln` | 1 234,56 zł |
| Pełna cena kWh | `formatPrice` | 0,40 zł/kWh |
| Składnik ceny kWh (energia, dystrybucja, opłaty, VAT) | `formatRate` | 0,089 zł |
| Energia | `formatKwh` | 12,34 kWh |
| Moc | `formatKw`, `formatKwp` | 2,50 kW, 6,00 kWp |
| Udział jako procent | `formatPercent(0.123)` | 12,3% |
| Temperatura | `formatDegrees(v)`, `formatDegrees(v, 1)` | 21°C, 20,6°C |
| Doba RRRR-MM-DD | `formatDate`, `formatDayMonth` | 27.11.2026, 27.11 |
| Doba słowami | `formatDayWords`, `formatWeekdayDay`, `formatWeekdayDayYear` | 27 listopada, piątek, 27 listopada |
| Moment (ISO z godziną) | `formatTime`, `formatDateTime` | 14:30, 27.11.2026, 14:30 |

- Tysiące zawsze ze spacją, także w liczbach czterocyfrowych (1 234,56); domyślny pl-PL pisze 1234,56.
- Cena kWh ma dwa miejsca po przecinku na każdym ekranie. Trzy miejsca mają tylko składniki ceny w rozbiciu,
  bo małe stawki (np. 0,012 zł) przy dwóch miejscach znikałyby.
- Momenty pokazujemy w czasie polskim, niezależnie od strefy przeglądarki. Czas bez strefy z backendu
  (np. data wgrania pliku) traktujemy jako UTC.

## Przyciski, karty, komunikaty i tabele

Klasy są w `frontend/src/components/uiStyles.js` i stosujemy je wprost na `<button>`, `<Link>`, `<div>` itd.

- **Przyciski:** `buttonClass(wariant, rozmiar)` z wariantami `primary`, `secondary`, `danger`, `dangerOutline`
  i rozmiarami `sm`, `md`, `lg`; skróty `PRIMARY_BUTTON`, `SECONDARY_BUTTON`. Przycisk z samą ikoną to
  `ICON_BUTTON` (z `aria-label`), link tekstowy w kolorze akcji to `LINK_BUTTON`.
- **Karty:** `CARD` (zwykła), `CARD_FLUSH` (tabela przy krawędziach), `STAT_CARD` (kafelek z kolorowym paskiem,
  kolor paska dodaje ekran) i `EMPTY_CARD` (pusty stan ekranu).
- **Komunikaty:** `alertClass("error" | "warning" | "info" | "success")`. Błąd ma `role="alert"`.
- **Tabele:** `TABLE` (albo `WIDE_TABLE` dla tabel z długimi godzinami, które na telefonie przewijają się
  w poziomie), `TABLE_HEAD`, `TABLE_BODY`, `TH`, `TH_NUMBER`, `TD`, `TD_NUMBER`. Liczby i kwoty do prawej.

## Stany wywołań API

Każde wywołanie API ma stan ładowania (szkielet albo „Ładowanie…”), brak danych (np. `NoFileData`,
`NoDataInRange`) i błąd po polsku z `getApiErrorMessage`. Karta dodatkowa, której brak danych nie jest błędem
(np. prognoza PV na pulpicie bez paneli w profilu), może się wtedy nie pokazywać, ale przy błędzie serwera mówi,
że nie udało się pobrać danych.

## Telefon

Poniżej 768 px (`useIsPhone` z `hooks/useMediaQuery.js`) część ekranów pokazuje inny układ niż na komputerze,
zamiast przewijać szeroki widok w bok:

| Ekran | Na telefonie |
|---|---|
| Mój dom | Pokoje jako karty jedna pod drugą (`HouseRooms`), w każdej kafelki urządzeń z ikonami jak w przekroju; stuknięcie otwiera panel od dołu ekranu ze stanem i sterowaniem (włącz, wyłącz, program) |
| Plan na jutro, Optymalizacja | Karta na urządzenie (`ActionCards`) zamiast tabeli; długie listy okresów zwinięte do trzech |
| Taryfy (szczegóły rachunku) | Okres i kwota brutto w wierszu, składniki po rozwinięciu |
| Okna dialogowe | Na cały ekran |

Poza tym: pola formularzy mają na telefonie czcionkę 16 px (iPhone przy mniejszej powiększa ekran),
wysokość układu to `h-dvh` (pasek adresu nie ucina dołu), a ważne informacje nie są tylko w `title`
(podpowiedź po najechaniu myszą), lecz w tekście albo pod „Dlaczego?” / „Jak to liczymy” (`MoreInfo`).
W testach (jsdom) `matchMedia` nie istnieje, więc ekrany renderują układ komputerowy; widok telefonu test
włącza, podstawiając `matchMedia` (np. `HouseRooms.test.jsx`).

## Aplikacja na telefon (PWA)

`vite-plugin-pwa` (w `vite.config.js`) tworzy manifest (`manifest.webmanifest`: nazwa, kolory, start na
`/dashboard`, tryb bez paska przeglądarki) i service worker (`sw.js`). Ikony są w `public/icons`
(192, 512, maskowana 512 dla Androida, 180 dla iPhone'a).

- Service worker trzyma tylko pliki aplikacji. Dane z API zawsze idą z sieci, żeby nie pokazać starych cen,
  stanu domu ani planu.
- Rejestracja jest w `src/pwa/registerServiceWorker.js` (wywoływana z `main.jsx`). Nową wersję włącza
  użytkownik paskiem „Jest nowa wersja aplikacji · Odśwież” (`AppStatusBanner`), ten sam komponent mówi
  o braku internetu.
- nginx serwuje `sw.js`, pliki workbox i manifest bez cache, żeby telefon od razu wykrył nową wersję.
- API jest pod tym samym adresem co aplikacja (`/api/v1`, nginx przekazuje do backendu), więc aplikacja działa
  z telefonu pod adresem IP komputera w tej samej sieci Wi-Fi, np. `http://192.168.1.23:5173`.
- iPhone: Safari → Udostępnij → Do ekranu początkowego. Działa też przez `http://` w sieci domowej (ikona,
  pełny ekran); service worker (szybszy start, pasek nowej wersji) włącza się tylko przez HTTPS.
- Android/Chrome: „Zainstaluj aplikację” tylko przez HTTPS albo `localhost`; przez `http://IP` jest
  „Dodaj do ekranu głównego” (skrót do strony).
- Limity logowania liczą się dla adresu telefonu: nginx podaje go w `X-Real-IP`, a backend ufa temu nagłówkowi
  tylko od kontenera `frontend` (`TRUSTED_PROXY_HOST`). Wyjątek: Docker Desktop (Windows, macOS) podmienia adres
  klienta przy przekierowaniu portu na bramę sieci Dockera (np. `172.21.0.1`), więc lokalnie wszystkie urządzenia
  dzielą jeden licznik. Na serwerze z Linuksem adres klienta dociera prawdziwy.

## Sprawdzenie ekranów

Każdy ekran sprawdzamy na szerokości 375 px (telefon) i 1440 px (komputer): bez poziomego przewijania strony,
z menu zamykanym po wyborze pozycji.

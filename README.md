# Energy Advisor

Aplikacja webowa do analizy zużycia energii elektrycznej. Na podstawie pliku z odczytami licznika
porównuje koszt energii w taryfach G11, G12 oraz w taryfie dynamicznej opartej o Rynkową Cenę
Energii (RCE) publikowaną przez PSE.

## Architektura

| komponent | technologie | adres lokalny |
|---|---|---|
| Backend (REST API) | Python 3.11, FastAPI, SQLAlchemy, Alembic | http://localhost:8000, dokumentacja: `/docs` |
| Frontend | React, Vite, Tailwind CSS | http://localhost:5173 |
| Baza danych | PostgreSQL 15 | `localhost:5432` |
| Worker cen dynamicznych | APScheduler | – |

Wszystkie komponenty działają w kontenerach zdefiniowanych w `docker-compose.yml`. Frontend
w kontenerze to zbudowana wersja serwowana przez nginx; do pracy nad kodem frontendu można
uruchomić go lokalnie przez Vite (krok 6).

## Wymagania

- Docker i Docker Compose
- Node.js 22+ (tylko do lokalnego uruchamiania frontendu przez Vite)
- Python 3.11 (opcjonalnie, do uruchamiania testów poza kontenerem)

## Uruchomienie

### 1. Konfiguracja

```bash
cp .env.example .env
```

W pliku `.env` należy uzupełnić co najmniej `POSTGRES_PASSWORD`, `JWT_SECRET_KEY` oraz
`PRICE_SYNC_ADMIN_KEY`. Plik jest wspólny dla Docker Compose, backendu i frontendu.
Opis zmiennych znajduje się w `.env.example`.

Sekrety (`JWT_SECRET_KEY`, `PRICE_SYNC_ADMIN_KEY`, `HUB_API_KEY`) muszą mieć co najmniej 32 znaki,
a backend i hub nie wystartują z wartościami-zaślepkami z `.env.example`. Losowe wartości wypisuje:

```bash
python backend/scripts/generate_secrets.py
```

### 2. Kontenery

```bash
docker compose up -d --build
```

### 3. Migracje bazy danych

Migracje są uruchamiane automatycznie przed startem backendu. Dla już działającego
środowiska można uruchomić je jednorazowo ręcznie:

```bash
docker compose exec backend alembic upgrade head
```

Cofanie migracji (`alembic downgrade`) działa tylko do migracji `a1b2c3d4e5f6`. Dodaje ona wartość
do typu enum, a PostgreSQL nie potrafi jej usunąć, więc aby cofnąć się dalej, trzeba odtworzyć
bazę od zera albo z kopii.

### 4. Dane początkowe (taryfy)

Cennik (stawki dystrybucyjne i sprzedaży, opłaty regulacyjne) jest w plikach JSON w `backend/data/tariffs`
(format: [docs/tariff-data-format.md](docs/tariff-data-format.md)). Ładuje się go skryptem, który waliduje
pliki i zapisuje wszystko w jednej transakcji; ponowne uruchomienie nie tworzy duplikatów:

```bash
docker compose exec backend python scripts/load_tariffs.py data/tariffs
docker compose exec backend python scripts/load_tariffs.py --check data/tariffs   # tylko walidacja, bez bazy
```

### 5. Ceny dynamiczne

Ceny RCE zapisywane są w tabeli `rce_price_observations` i są niezależne od cennika z kroku 4
(oferta z ceną dynamiczną przechowuje marżę sprzedawcy doliczaną do ceny rynkowej).

**Synchronizacja bieżąca.** Kontener `price-worker` uruchamia się w kroku 2 i czeka do 5 minut na
utworzenie tabel przez migracje. Następnie pobiera ceny z ostatnich 7 dni i na dzień następny,
a później powtarza to codziennie o 15:00 (Europe/Warsaw). Zakończenie synchronizacji startowej
widoczne jest w logach:

```bash
docker compose logs -f price-worker
# ... INFO price_sync_worker: Synchronizacja zakończona: status=success, rekordy=...
```

Jeśli migracje zostały wykonane później niż 5 minut po starcie kontenerów, synchronizacja startowa
jest pomijana (log: `Pomijam synchronizację startową`). Należy wtedy zrestartować workera:
`docker compose restart price-worker`.

**Ceny historyczne (backfill).** Starsze ceny pobiera się jednorazowo, w działającym kontenerze
workera, **po zakończeniu synchronizacji startowej**:

```bash
docker compose exec price-worker python -m app.workers.price_sync_worker backfill 2024-06-14 2025-12-31
```

Synchronizacje wykluczają się wzajemnie (blokada w bazie), więc backfill uruchomiony w trakcie
synchronizacji startowej zakończy się błędem `Synchronizacja cen jest już w toku`. W takim
przypadku należy poczekać na wpis w logach i uruchomić polecenie ponownie.

Dane PSE są dostępne od 2024-06-14. Backfill pobiera je w paczkach po 31 dni; ponowne uruchomienie
dla tego samego zakresu aktualizuje istniejące rekordy i nie tworzy duplikatów.
Szczegóły: [docs/dynamic-prices.md](docs/dynamic-prices.md).

Net-billing (nowelizacja ustawy o OZE, Dz.U. 2024 poz. 1847):

- do 31.01.2025 energię oddaną do sieci wyceniamy po RCE z każdego kwadransa;
- od 1.02.2025 według wyboru w profilu: RCEm (miesięczna; domyślna dla instalacji, które pierwszy raz
  oddały energię przed 1.07.2024) albo RCE (nowsze instalacje i ci, którzy złożyli oświadczenie);
- od 1.02.2025 wartość energii w depozycie powiększa się o współczynnik 1,23;
- ujemna cena rynkowa daje wartość 0.

Ceny RCEm worker pobiera ze strony PSE (tabela `rcem_price_observations`) przy starcie i codziennie
o 15:30. Ręcznie: `docker compose exec price-worker python -m app.workers.price_sync_worker rcem`.

Nie modelujemy zwrotu niewykorzystanej nadpłaty (do 20% przy RCEm, 30% przy RCE) — depozyt pokrywa
tylko energię czynną.

**Pogoda.** Kontener `weather-worker` pobiera z Open-Meteo prognozę (co 3 h) i historię pogody dla dni
z wgranych plików (tabela `weather_observations`). Ręcznie:
`docker compose exec weather-worker python -m app.workers.weather_worker forecast` (albo `history`).
Szczegóły: [docs/weather.md](docs/weather.md).

### 6. Frontend

**W kontenerze.** Kontener `frontend` startuje w kroku 2 razem z resztą usług. Aplikacja jest
dostępna pod http://localhost:5173. Obraz buduje produkcyjną wersję aplikacji (`npm run build`)
i serwuje ją przez nginx, więc zmiany w kodzie nie są widoczne na bieżąco.

Zmienne `VITE_API_URL` i `VITE_GOOGLE_CLIENT_ID` są wpisywane w kod podczas budowania obrazu.
Po ich zmianie w `.env` albo po zmianach w kodzie trzeba przebudować obraz:

```bash
docker compose up -d --build frontend
```

**Lokalnie przez Vite (praca nad kodem).** Vite przeładowuje stronę po każdej zmianie w kodzie.
Kontener i Vite używają tego samego portu 5173, więc najpierw trzeba zatrzymać kontener:

```bash
docker compose stop frontend
cd frontend
npm install
npm run dev
```

Powrót do wersji z kontenera: zatrzymać Vite i wykonać `docker compose start frontend`.

## Dokumentacja

- [Ceny dynamiczne](docs/dynamic-prices.md): źródło danych, worker synchronizacji, wycena taryfy dynamicznej
- [Pogoda](docs/weather.md): co trzymamy w bazie, skąd która doba, worker pogody i endpoint
- [Prognoza PV](docs/pv-forecast.md): model, kalibracja na historii domu, jakość i co robimy bez pogody
- [Testy](docs/testing.md): uruchamianie testów, CI, fixtures i testy izolacji danych użytkowników
- [Jak przechowujemy dane](docs/privacy-and-data.md): jakie dane zbieramy, po co, gdzie, jak długo i kto ma do nich dostęp

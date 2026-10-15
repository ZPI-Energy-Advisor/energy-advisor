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

Backend, baza i worker działają w kontenerach zdefiniowanych w `docker-compose.yml`.
Frontend uruchamiany jest lokalnie przez Vite.

## Wymagania

- Docker i Docker Compose
- Node.js 20+
- Python 3.11 (opcjonalnie, do uruchamiania testów poza kontenerem)

## Uruchomienie

### 1. Konfiguracja

```bash
cp .env.example .env
```

W pliku `.env` należy uzupełnić co najmniej `POSTGRES_PASSWORD`, `JWT_SECRET_KEY` oraz
`PRICE_SYNC_ADMIN_KEY`. Plik jest wspólny dla Docker Compose, backendu i frontendu.
Opis zmiennych znajduje się w `.env.example`.

### 2. Kontenery

```bash
docker compose up -d --build
```

### 3. Migracje bazy danych

Migracje nie są uruchamiane automatycznie przy starcie kontenera.

```bash
docker compose exec backend alembic upgrade head
```

### 4. Dane początkowe (taryfy)

Taryfy G11, G12 i dynamiczna są wymagane do obliczania kosztów. Skrypt jest idempotentny:
nie wprowadza zmian, jeśli taryfy istnieją już w bazie.

```bash
docker compose exec backend python seed.py
```

### 5. Ceny dynamiczne

Ceny RCE zapisywane są w tabeli `dynamic_price_observations` i są niezależne od taryf z kroku 4
(taryfa dynamiczna przechowuje jedynie narzut i stawkę VAT doliczane do ceny rynkowej).

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

### 6. Frontend

```bash
cd frontend
npm install
npm run dev
```

## Dokumentacja

- [Ceny dynamiczne](docs/dynamic-prices.md): źródło danych, worker synchronizacji, wycena taryfy dynamicznej
- [Testy](docs/testing.md): uruchamianie testów, CI, fixtures i testy izolacji danych użytkowników

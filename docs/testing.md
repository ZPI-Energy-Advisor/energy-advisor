# Testy

Testy backendu (pytest) znajdują się w `backend/tests`. Wspólna infrastruktura (baza testowa,
użytkownicy, klienci HTTP z tokenami) jest zdefiniowana w `backend/tests/conftest.py`.

## Uruchamianie

W kontenerze backendu:

```bash
docker compose exec backend python -m pytest tests/
```

Poza kontenerem (z katalogu `backend`, przy uruchomionym kontenerze bazy):

```bash
POSTGRES_HOST=localhost python -m pytest tests/
```

Lint (wersja zgodna z CI):

```bash
pip install ruff==0.16.10
ruff check .
```

Testy korzystają z osobnej bazy `<POSTGRES_DB>_test`, którą `tests/conftest.py` tworzy i migruje
przy starcie. Jeśli baza jest niedostępna, testy wymagające bazy są pomijane.

## CI

Workflowy w [.github/workflows](../.github/workflows) uruchamiają dla każdego pull requesta do `main`:

- backend: lint (ruff), migracje Alembic na czystej bazie, testy (pytest),
- frontend: build produkcyjny (Vite).

Zielony wynik obu workflowów jest wymagany do zmergowania pull requesta.

## Fixtures

Wspólne fixtures zdefiniowane w `backend/tests/conftest.py`:

| fixture | opis |
|---|---|
| `db` | sesja bazy testowej; po teście usuwa utworzonych użytkowników wraz z ich danymi |
| `user_a`, `user_b` | dwóch niezależnych użytkowników |
| `client_a`, `client_b` | `TestClient` uwierzytelniony tokenem odpowiednio `user_a` i `user_b` |
| `anonymous_client` | `TestClient` bez tokenu |
| `make_token` | generator JWT, np. `make_token(user.id, expires_in=timedelta(minutes=-1))` zwraca token wygasły |
| `new_email` | unikalny adres e-mail do rejestracji przez API |

## Test izolacji dla nowego endpointu

Izolacja danych użytkowników jest weryfikowana w
[backend/tests/test_isolation.py](../backend/tests/test_isolation.py) na dwa sposoby.

**Wymaganie tokenu (401).** Lista endpointów jest pobierana ze schematu OpenAPI aplikacji, więc
każdy nowy endpoint jest automatycznie sprawdzany pod kątem odrzucenia żądania bez tokenu,
z niepoprawnym tokenem, z tokenem wygasłym oraz z refresh tokenem. Endpointy publiczne należy
dodać do zbioru `PUBLIC_ENDPOINTS` wraz z komentarzem uzasadniającym wyjątek.

**Dostęp do cudzych zasobów (404).** Endpoint operujący na zasobie należącym do użytkownika
(np. `/api/v1/devices/{device_id}`) należy zarejestrować w słowniku `OWNED_RESOURCES`:

```python
def _create_device(db, user):
    device = Device(user_id=user.id, name="Pralka")
    db.add(device)
    db.commit()
    return device.id


OWNED_RESOURCES = {
    ...
    "device": OwnedResource(
        create=_create_device,          # tworzy zasób należący do użytkownika i zwraca jego id
        read="/api/v1/devices/{id}",    # ścieżka odczytu
        delete="/api/v1/devices/{id}",  # ścieżka usunięcia (opcjonalna)
    ),
}
```

Na podstawie wpisu generowane są testy sprawdzające, że:

- właściciel ma dostęp do zasobu (200),
- inny użytkownik otrzymuje 404 przy odczycie i usunięciu, a zasób pozostaje nienaruszony,
- odwołanie do nieistniejącego id zwraca 404.

Cudzy zasób zwraca 404, a nie 403, aby nie ujawniać jego istnienia. W warstwie serwisu oznacza to
pobieranie zasobu zawsze z filtrem po właścicielu (np. `get_by_id_for_user(resource_id, user.id)`).

Endpointy zwracające listy lub agregaty (bez identyfikatora w ścieżce) wymagają osobnego testu,
analogicznego do `test_lists_and_aggregates_show_only_own_data`, sprawdzającego, że dane `user_a`
nie pojawiają się w odpowiedzi dla `client_b`.

# Symulacja Smart Home

Kontrakt API: [`docs/smart-home-api.md`](../docs/smart-home-api.md).

## Mikroserwis urządzenia

Jeden kod sterownika (`device/`), który hub uruchamia osobno dla każdego urządzenia z rejestru:

```bash
python -m device --config device.json
```

Plik konfiguracji to obiekt urządzenia z pliku urządzeń oraz `port` i `bind_host`.

| Plik | Odpowiedzialność |
|---|---|
| `device/driver.py` | Stan urządzenia i naliczanie energii, bez HTTP |
| `device/api.py` | Endpointy i format błędów z kontraktu |
| `device/models.py` | Modele konfiguracji i żądań |
| `device/__main__.py` | Wczytanie konfiguracji i start serwera |

Urządzenie nie ma własnego zegara. Czas płynie tylko przez `POST /tick`, więc bez ticków program
nie postępuje i energia nie rośnie.

Sterownik można uruchomić ręcznie i otworzyć Swaggera pod `http://127.0.0.1:<port>/docs`.

## Hub

Serwis (`hub/`), z którym rozmawia backend. Stawia mikroserwisy urządzeń według rejestru, pilnuje
ich, przekazuje komendy, odmierza czas symulacji i wysyła zdarzenia urządzeń do backendu (webhook
`POST /api/v1/home/events` pod `BACKEND_URL`).

| Plik | Odpowiedzialność |
|---|---|
| `hub/supervisor.py` | Rekoncyliacja rejestru, procesy urządzeń, health-check, komendy, ticki, zaplanowane starty i zdarzenia z ticków |
| `hub/webhook.py` | Kolejka zdarzeń dla backendu, wysyłka partiami i ponawianie |
| `hub/clock.py` | Zegar symulacji: czas, pauza, tempo i odmierzanie kroku, bez HTTP |
| `hub/api.py` | Endpointy, klucz `X-Hub-Api-Key` i format błędów |
| `hub/state.py` | Plik stanu: rejestr z portami, odtwarzany po restarcie huba |
| `hub/models.py` | Modele żądań |
| `hub/config.py` | Ustawienia ze zmiennych środowiskowych |

Hub wymaga `HUB_API_KEY` w `.env`; bez `BACKEND_URL` działa, ale nie wysyła zdarzeń. Uruchomienie:

```bash
docker compose up hub
```

Tryb demo otwiera hub i sterowniki na `127.0.0.1`, np. Swagger pralki pod `http://127.0.0.1:9101/docs`:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up hub
```

### Zużycie pamięci

Pomiar dla pliku przykładowego w kontenerze `python:3.11-slim`, po starcie, bez ticków:

| Pomiar | Wynik |
|---|---|
| Hub i 24 urządzenia, `docker stats` | około 806 MiB |
| Na jeden proces | około 32 MiB |
| Pełny rejestr na 50 portów (oszacowanie) | około 1,6 GiB |

Każde urządzenie to osobny proces Pythona z FastAPI, więc pamięć rośnie liniowo z ich liczbą.

## Testy

Z katalogu `smart-home-hub`:

```bash
pip install -r requirements.txt
python -m pytest tests/
ruff check .
```

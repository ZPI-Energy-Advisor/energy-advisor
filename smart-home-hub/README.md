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

## Testy

Z katalogu `smart-home-hub`:

```bash
pip install -r requirements.txt
python -m pytest tests/
ruff check .
```

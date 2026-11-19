"""Ustawienia cen dynamicznych z env. Osobno od app.config, bo worker cen nie dostaje sekretów backendu (JWT)."""

import os
from datetime import time

from dotenv import load_dotenv

load_dotenv()

# Godzina (Europe/Warsaw), o której worker pobiera ceny na jutro i od której są dostępne w aplikacji.
# PSE publikuje je ok. 13:45.
PRICE_PUBLICATION_TIME = time.fromisoformat(os.getenv("PRICE_PUBLICATION_TIME") or "15:00")
# Ceny doby są „płaskie”, gdy najdroższy i najtańszy kwadrans różnią się o mniej niż tyle zł/kWh.
FLAT_PRICE_SPREAD_PLN_KWH = float(os.getenv("FLAT_PRICE_SPREAD_PLN_KWH") or 0.05)

import os
from datetime import time

from dotenv import load_dotenv


load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY must be configured")

SIGNATURE_ALGORITHM = os.getenv("SIGNATURE_ALGORITHM", "HS256")
if SIGNATURE_ALGORITHM != "HS256":
    raise RuntimeError("Only HS256 is supported")

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID") or None

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRATION_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRATION_DAYS", "7"))

CORS_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

PRICE_SYNC_ADMIN_KEY = os.getenv("PRICE_SYNC_ADMIN_KEY") or None
# Godzina (Europe/Warsaw), o której worker pobiera ceny na jutro i od której są dostępne w aplikacji.
# PSE publikuje je ok. 13:45.
PRICE_PUBLICATION_TIME = time.fromisoformat(os.getenv("PRICE_PUBLICATION_TIME") or "15:00")
# Ceny doby są „płaskie”, gdy najdroższy i najtańszy kwadrans różnią się o mniej niż tyle zł/kWh.
FLAT_PRICE_SPREAD_PLN_KWH = float(os.getenv("FLAT_PRICE_SPREAD_PLN_KWH") or 0.05)

HUB_URL = os.getenv("HUB_URL") or None
HUB_API_KEY = os.getenv("HUB_API_KEY") or None
HUB_TIMEOUT_SECONDS = float(os.getenv("HUB_TIMEOUT_SECONDS") or 5)
HUB_HOME_USER_EMAIL = (os.getenv("HUB_HOME_USER_EMAIL") or "").strip().lower() or None

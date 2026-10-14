import os

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

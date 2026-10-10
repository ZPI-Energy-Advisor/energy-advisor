import os

from dotenv import load_dotenv


load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY must be configured")

SIGNATURE_ALGORITHM = os.getenv("SIGNATURE_ALGORITHM", "HS256")
if SIGNATURE_ALGORITHM != "HS256":
    raise RuntimeError("Only HS256 is supported")

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
if not CLIENT_ID:
    raise RuntimeError("GOOGLE_CLIENT_ID must be configured")

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRATION_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRATION_DAYS", "7"))

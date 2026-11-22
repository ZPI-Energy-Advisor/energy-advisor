"""Wypisuje losowe sekrety do wklejenia w .env (nadpisują zaślepki z .env.example).

Użycie: python backend/scripts/generate_secrets.py
"""

import secrets

SECRET_NAMES = ("JWT_SECRET_KEY", "PRICE_SYNC_ADMIN_KEY", "HUB_API_KEY")


def generate() -> dict[str, str]:
    return {name: secrets.token_urlsafe(48) for name in SECRET_NAMES}


if __name__ == "__main__":
    for name, value in generate().items():
        print(f"{name}={value}")

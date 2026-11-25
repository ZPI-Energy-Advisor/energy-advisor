from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status

from app.core.errors import ContractError


# Wersja polityki prywatności (data publikacji). Po każdej zmianie treści w app/legal/privacy_policy.md
# trzeba ją podbić: użytkownicy z akceptacją starszej wersji zostaną poproszeni o ponowną akceptację.
PRIVACY_POLICY_VERSION = "2026-11-23"

POLICY_FILE = Path(__file__).resolve().parents[1] / "legal" / "privacy_policy.md"

POLICY_REQUIRED_CODE = "privacy_policy_required"
POLICY_REQUIRED_MESSAGE = "Zapoznaj się z aktualną polityką prywatności i ją zaakceptuj."

SOURCE_REGISTER = "register"
SOURCE_GOOGLE = "google"
SOURCE_REACCEPT = "reaccept"


@lru_cache(maxsize=1)
def privacy_policy_content() -> str:
    return POLICY_FILE.read_text(encoding="utf-8")


def is_current_version(version: str | None) -> bool:
    return version == PRIVACY_POLICY_VERSION


def require_current_version(version: str | None) -> None:
    """Akceptacja przy rejestracji i ponownej akceptacji musi dotyczyć wersji, którą serwer teraz publikuje."""
    if not is_current_version(version):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=POLICY_REQUIRED_MESSAGE)


def policy_required_error() -> ContractError:
    """Nowe konto Google bez akceptacji: frontend rozpoznaje kod, pokazuje politykę i ponawia logowanie."""
    return ContractError(status.HTTP_403_FORBIDDEN, POLICY_REQUIRED_CODE, POLICY_REQUIRED_MESSAGE)

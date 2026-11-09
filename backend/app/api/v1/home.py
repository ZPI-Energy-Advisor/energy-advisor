from fastapi import APIRouter, Depends

from app.api.v1.deps import get_home_owner, get_home_service
from app.models.User import User
from app.schemas.smart_home import HomeStatus
from app.services.home_service import HomeService



router = APIRouter(
    prefix="/home",
    tags=["Smart Home"],
)


@router.get("", response_model=HomeStatus)
def get_home(
    owner: User = Depends(get_home_owner),
    service: HomeService = Depends(get_home_service),
):
    """Czy dom jest podłączony i czy hub ma aktualny rejestr urządzeń."""
    return service.status(owner)


@router.post("/connect", response_model=HomeStatus)
def connect_home(
    owner: User = Depends(get_home_owner),
    service: HomeService = Depends(get_home_service),
):
    """Podłącza dom i wysyła do huba rejestr urządzeń; ponowne wywołanie wysyła go jeszcze raz.

    Niedostępny hub nie cofa podłączenia: odpowiedź ma `sync.status = pending` i powód w `sync.error`.
    """
    return service.connect(owner)


@router.delete("", response_model=HomeStatus)
def disconnect_home(
    owner: User = Depends(get_home_owner),
    service: HomeService = Depends(get_home_service),
):
    """Odłącza dom: hub dostaje pusty rejestr i zatrzymuje urządzenia."""
    return service.disconnect(owner)

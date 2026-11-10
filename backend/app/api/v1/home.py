from fastapi import APIRouter, Depends, status

from app.api.v1.deps import (
    get_home_event_service,
    get_home_owner,
    get_home_service,
    get_home_state_service,
    require_hub_api_key,
)
from app.models.User import User
from app.schemas.smart_home import HomeState, HomeStatus, HubEventBatch, HubEventsAccepted
from app.services.home_event_service import HomeEventService
from app.services.home_service import HomeService
from app.services.home_state_service import HomeStateService



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


@router.get("/state", response_model=HomeState)
def get_home_state(
    owner: User = Depends(get_home_owner),
    service: HomeStateService = Depends(get_home_state_service),
):
    """Zegar, stany i moc urządzeń z huba oraz zużycie i koszt od początku doby symulacji."""
    return service.state(owner)


@router.post(
    "/events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=HubEventsAccepted,
    dependencies=[Depends(require_hub_api_key)],
)
def receive_hub_events(
    batch: HubEventBatch,
    service: HomeEventService = Depends(get_home_event_service),
):
    """Webhook huba: partia zdarzeń urządzeń. """
    return service.ingest(batch)

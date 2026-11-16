from fastapi import APIRouter, Depends, status

from app.api.v1.deps import (
    get_home_control_service,
    get_home_event_service,
    get_home_owner,
    get_home_service,
    get_home_state_service,
    require_hub_api_key,
)
from app.models.User import User
from app.schemas.smart_home import (
    CommandResult,
    DeviceCommand,
    HomeClockState,
    HomeClockUpdate,
    HomeState,
    HomeStatus,
    HubEventBatch,
    HubEventsAccepted,
)
from app.services.home_control_service import HomeControlService
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
    "/devices/{device_id}/commands",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommandResult,
)
def send_device_command(
    device_id: str,
    command: DeviceCommand,
    owner: User = Depends(get_home_owner),
    service: HomeControlService = Depends(get_home_control_service),
):
    """Polecenie dla urządzenia domu przekazywane do huba: on, off albo start_program."""
    return service.send_command(owner, device_id, command)


@router.put("/clock", response_model=HomeClockState)
def update_home_clock(
    update: HomeClockUpdate,
    owner: User = Depends(get_home_owner),
    service: HomeControlService = Depends(get_home_control_service),
):
    """Start, pauza i tempo zegara symulacji. `day` zaczyna symulację od północy tej doby (tylko przy pauzie)."""
    return service.update_clock(owner, update)


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
    """Webhook huba: partia zdarzeń urządzeń."""
    return service.ingest(batch)

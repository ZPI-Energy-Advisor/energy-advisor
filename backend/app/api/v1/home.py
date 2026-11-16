from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import (
    get_home_control_service,
    get_home_event_service,
    get_home_owner,
    get_home_service,
    get_home_state_service,
    get_plan_run_service,
    require_hub_api_key,
)
from app.models.User import User
from app.schemas.plan_run import PlanRunOut, PlanRunRequest
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
from app.services.plan_run_service import PlanRunService


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


@router.post("/plan-runs", status_code=status.HTTP_201_CREATED, response_model=PlanRunOut)
def start_plan_run(
    request: PlanRunRequest,
    owner: User = Depends(get_home_owner),
    service: PlanRunService = Depends(get_plan_run_service),
):
    """Uruchamia zatwierdzony plan dnia w symulacji od północy jego doby (ZP-113).

    Hub dostaje jednym żądaniem pozycje planu i historię dnia referencyjnego (produkcja PV, pompa ciepła
    albo bojler odznaczone w planie), a zegar rusza. Urządzenia stałe startują wyłączone. Ponowne
    uruchomienie zaczyna dobę od nowa.
    """
    return service.start(owner, request.plan_id)


@router.get("/plan-runs/latest", response_model=PlanRunOut | None)
def get_latest_plan_run(
    owner: User = Depends(get_home_owner),
    service: PlanRunService = Depends(get_plan_run_service),
):
    """Ostatni przebieg planu: status, energia urządzeń z planu (plan i symulacja) oraz awarie urządzeń."""
    return service.latest(owner)


@router.post("/plan-runs/{run_id}/end", response_model=PlanRunOut)
def end_plan_run(
    run_id: UUID,
    owner: User = Depends(get_home_owner),
    service: PlanRunService = Depends(get_plan_run_service),
):
    """„Zakończ”: zatrzymuje zegar, kasuje resztę planu w kolejce huba i zamyka przebieg.

    Zakończony przebieg zostaje bez zmian.
    """
    return service.end(owner, run_id)


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

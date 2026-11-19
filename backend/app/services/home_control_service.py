"""Sterowanie domem z ekranu właściciela: komendy urządzeń i zegar symulacji.

Backend tylko przekazuje polecenia do huba, który jest jedynym źródłem stanu urządzeń i czasu
symulacji. Błędy huba zamieniamy na odpowiedzi dla przeglądarki: opisy z huba (np. „Trwa program
urządzenia”) przechodzą bez zmian, a awarie huba i błędna konfiguracja dostają własne komunikaty.
"""

import logging
from datetime import date, datetime, time

from fastapi import HTTPException, status

from app.clients.hub_client import HubAuthError, HubClient, HubError, HubUnavailableError
from app.models.User import User
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.home_repository import HomeRepository
from app.schemas.smart_home import (
    MAX_BATCH_COMMANDS,
    CommandResult,
    DeviceCommand,
    HomeClockState,
    HomeClockUpdate,
    HubClock,
    HubCommand,
    HubCommandResult,
)
from app.services.home_service import AUTH_MESSAGE, DISABLED_MESSAGE, require_connected


logger = logging.getLogger(__name__)

HUB_UNAVAILABLE_MESSAGE = "Hub Smart Home jest niedostępny. Spróbuj ponownie za chwilę."
INVALID_RESPONSE_MESSAGE = "Hub Smart Home zwrócił odpowiedź niezgodną z kontraktem."
DEVICE_UNREACHABLE_MESSAGE = "Urządzenie nie odpowiada. Hub uruchomi je ponownie, spróbuj za chwilę."
CLOCK_RESET_FAILED_MESSAGE = "Nie wszystkie urządzenia przyjęły nową dobę. Ustaw dobę ponownie."
UNCONFIRMED_COMMAND_MESSAGE = (
    "Hub nie potwierdził polecenia na czas i mógł je wykonać. Sprawdź stan urządzenia, zanim wyślesz je ponownie."
)


def hub_http_error(error: HubError, unreachable_message: str = DEVICE_UNREACHABLE_MESSAGE) -> HTTPException:
    """Błąd huba jako odpowiedź API. Odrzucenie polecenia z kodem kontraktu (4xx) zachowuje status i opis huba."""
    if isinstance(error, HubAuthError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=AUTH_MESSAGE)
    if error.code == "device_unreachable":
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=unreachable_message)
    if isinstance(error, HubUnavailableError):
        if error.status_code is None and not error.retryable:
            # Brak odpowiedzi na POST: hub mógł wykonać komendę, więc „spróbuj ponownie” mogłoby ją powtórzyć.
            return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=UNCONFIRMED_COMMAND_MESSAGE)
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=HUB_UNAVAILABLE_MESSAGE)
    if error.status_code is not None and 400 <= error.status_code < 500 and error.code and error.detail:
        return HTTPException(status_code=error.status_code, detail=error.detail)
    # 4xx bez kodu kontraktu (np. brak trasy w starszym hubie) to błąd integracji, a nie żądania użytkownika.
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=INVALID_RESPONSE_MESSAGE)


def day_midnight(day: date) -> datetime:
    """Północ doby w strefie domu: przesunięcie strefy zależy od daty (czas letni i zimowy)."""
    return datetime.combine(day, time(0), tzinfo=LOCAL_TIMEZONE)


def require_hub(hub_client: HubClient | None, home_repository: HomeRepository, owner: User) -> HubClient:
    """Klient huba do sterowania domem: symulacja włączona i dom podłączony przez właściciela."""
    if hub_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DISABLED_MESSAGE)
    require_connected(home_repository.get(), owner)
    return hub_client


def update_hub_clock(hub_client: HubClient, **changes) -> HubClock:
    """Zmiana zegara huba; błąd huba jako odpowiedź API."""
    try:
        return hub_client.update_clock(**changes)
    except HubError as error:
        logger.warning("Hub nie zmienił zegara: %s", error)
        raise hub_http_error(error, unreachable_message=CLOCK_RESET_FAILED_MESSAGE) from error


def send_batch(hub_client: HubClient, commands: list[HubCommand], failure_message: str) -> list[HubCommandResult]:
    """Komendy doby jednym żądaniem do huba (POST /home/commands), z wynikiem dla każdej.

    Odrzucenie pojedynczej komendy jest w jej wyniku. Gdy zawiedzie całe żądanie (brak odpowiedzi, 5xx),
    nie wiemy, co hub przyjął, więc odpowiadamy `failure_message`: ponowne ustawienie doby resetuje
    urządzenia i kasuje zaplanowane komendy, więc ponowienie niczego nie wykona dwa razy.

    Doba ma zwykle kilkadziesiąt komend; ponad limit kontraktu dzielimy ją na kolejne żądania. Każda
    komenda ma bezwzględny `start_at`, więc podział nie zmienia tego, kiedy się wykona.
    """
    results: list[HubCommandResult] = []
    try:
        for first in range(0, len(commands), MAX_BATCH_COMMANDS):
            results.extend(hub_client.send_commands(commands[first:first + MAX_BATCH_COMMANDS]))
    except HubError as error:
        logger.warning("Hub nie przyjął partii %d komend: %s", len(commands), error)
        if isinstance(error, HubAuthError):
            raise hub_http_error(error) from error
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=failure_message) from error
    return results


class HomeControlService:
    def __init__(self, home_repository: HomeRepository, hub_client: HubClient | None):
        self.home_repository = home_repository
        self.hub_client = hub_client

    def _require_ready(self, owner: User) -> HubClient:
        return require_hub(self.hub_client, self.home_repository, owner)

    def send_command(self, owner: User, device_id: str, command: DeviceCommand) -> CommandResult:
        hub_client = self._require_ready(owner)
        try:
            return hub_client.send_command(device_id, command)
        except HubError as error:
            logger.warning("Hub nie wykonał komendy %s dla %s: %s", command.command.value, device_id, error)
            raise hub_http_error(error) from error

    def update_clock(self, owner: User, update: HomeClockUpdate) -> HomeClockState:
        hub_client = self._require_ready(owner)
        clock = update_hub_clock(
            hub_client,
            sim_time=day_midnight(update.day) if update.day else None,
            # Ustawienie doby zawsze zaczyna nową symulację, także gdy zegar już stoi na tej północy:
            # urządzenia wracają do stanu wyłączonego, a zaplanowane komendy znikają.
            restart=update.day is not None,
            running=update.running,
            speed=update.speed,
        )
        return HomeClockState(sim_time=clock.sim_time, running=clock.running, speed=clock.speed, stop_at=clock.stop_at)

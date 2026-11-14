"""Sterowanie domem z ekranu właściciela: komendy urządzeń i zegar symulacji.

Backend tylko przekazuje polecenia do huba, który jest jedynym źródłem stanu urządzeń i czasu
symulacji. Błędy huba zamieniamy na odpowiedzi dla przeglądarki: opisy z huba (np. „Trwa program
urządzenia”) przechodzą bez zmian, a awarie huba i błędna konfiguracja dostają własne komunikaty.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status

from app.clients.hub_client import HubAuthError, HubClient, HubError, HubUnavailableError
from app.models.User import User
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.home_repository import HomeRepository
from app.schemas.smart_home import (
    CommandResult,
    CommandType,
    DeviceCommand,
    HomeClockUpdate,
    HomeClockUpdated,
    HomeReplay,
    HubClock,
)
from app.services.home_replay import replay_runs
from app.services.home_service import AUTH_MESSAGE, DISABLED_MESSAGE, require_connected


logger = logging.getLogger(__name__)

HUB_UNAVAILABLE_MESSAGE = "Hub Smart Home jest niedostępny. Spróbuj ponownie za chwilę."
INVALID_RESPONSE_MESSAGE = "Hub Smart Home zwrócił odpowiedź niezgodną z kontraktem."
DEVICE_UNREACHABLE_MESSAGE = "Urządzenie nie odpowiada. Hub uruchomi je ponownie, spróbuj za chwilę."
CLOCK_RESET_FAILED_MESSAGE = "Nie wszystkie urządzenia przyjęły nową dobę. Ustaw dobę ponownie."
UNCONFIRMED_COMMAND_MESSAGE = (
    "Hub nie potwierdził polecenia na czas i mógł je wykonać. Sprawdź stan urządzenia, zanim wyślesz je ponownie."
)
# Kod huba dla urządzenia spoza jego rejestru: tylko takie urządzenia trafiają do skipped_devices.
DEVICE_NOT_FOUND = "device_not_found"
REPLAY_FAILED_MESSAGE = (
    "Doba została ustawiona, ale hub nie przyjął całego odtworzenia historii. Ustaw dobę ponownie."
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


class HomeControlService:
    def __init__(self, home_repository: HomeRepository, hub_client: HubClient | None):
        self.home_repository = home_repository
        self.hub_client = hub_client

    def _require_ready(self, owner: User) -> HubClient:
        if self.hub_client is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DISABLED_MESSAGE)
        require_connected(self.home_repository.get(), owner)
        return self.hub_client

    def send_command(self, owner: User, device_id: str, command: DeviceCommand) -> CommandResult:
        hub_client = self._require_ready(owner)
        try:
            return hub_client.send_command(device_id, command)
        except HubError as error:
            logger.warning("Hub nie wykonał komendy %s dla %s: %s", command.command.value, device_id, error)
            raise hub_http_error(error) from error

    def update_clock(self, owner: User, update: HomeClockUpdate) -> HomeClockUpdated:
        """Zmienia zegar w kolejności z kontraktu: doba, potem odtworzenie jej historii, na końcu start i tempo.

        Ustawienie doby resetuje urządzenia i kasuje zaplanowane komendy, więc odtworzenie trzeba
        zaplanować po nim, a przed startem zegara, żeby żadna akcja z historii nie wypadła w przeszłości.
        """
        hub_client = self._require_ready(owner)
        clock, replay = None, None
        if update.day is not None:
            # restart: także ta sama doba drugi raz zaczyna od pustej kolejki, więc nic nie odtworzy się podwójnie.
            clock = self._update_clock(hub_client, sim_time=day_midnight(update.day), restart=True)
            replay = self._replay_day(hub_client, owner, update.day)
        if update.running is not None or update.speed is not None:
            clock = self._update_clock(hub_client, running=update.running, speed=update.speed)
        return HomeClockUpdated(sim_time=clock.sim_time, running=clock.running, speed=clock.speed, replay=replay)

    @staticmethod
    def _update_clock(hub_client: HubClient, **changes) -> HubClock:
        try:
            return hub_client.update_clock(**changes)
        except HubError as error:
            logger.warning("Hub nie zmienił zegara: %s", error)
            raise hub_http_error(error, unreachable_message=CLOCK_RESET_FAILED_MESSAGE) from error

    def _replay_day(self, hub_client: HubClient, owner: User, day: date) -> HomeReplay:
        """Wysyła do huba akcje urządzeń fixed z doby `day` jako run_profile ze startem akcji.

        Urządzenie spoza rejestru huba (np. przy zaległej wysyłce) jest pomijane, a reszta doby się odtwarza.
        Inne odrzucenie pojedynczej akcji (np. zajęte urządzenie) liczymy w `rejected_actions`.
        Awaria huba w trakcie przerywa wysyłkę: ponowne ustawienie doby resetuje urządzenia i zaczyna od nowa,
        więc nic nie odtworzy się dwa razy.
        """
        start = day_midnight(day).astimezone(timezone.utc)
        end = day_midnight(day + timedelta(days=1)).astimezone(timezone.utc)
        runs = replay_runs(self.home_repository.fixed_action_slots(owner.id, start, end))
        replayed, skipped = set(), set()
        actions = rejected = 0
        for run in runs:
            command = DeviceCommand(
                command=CommandType.RUN_PROFILE,
                profile_kwh=run.profile_kwh,
                ref=run.ref,
                start_at=run.start.astimezone(LOCAL_TIMEZONE),
            )
            try:
                hub_client.send_command(run.device_id, command)
            except HubError as error:
                if not _rejected_by_contract(error):
                    logger.warning("Odtwarzanie doby %s przerwane po %d akcjach: %s", day, actions, error)
                    if isinstance(error, HubAuthError):
                        raise hub_http_error(error) from error
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=REPLAY_FAILED_MESSAGE) from error
                logger.warning("Hub odrzucił akcję %s urządzenia %s: %s", run.ref, run.device_id, error)
                if error.code == DEVICE_NOT_FOUND:
                    skipped.add(run.device_id)
                else:
                    rejected += 1
                continue
            actions += 1
            replayed.add(run.device_id)
        return HomeReplay(
            actions=actions, devices=len(replayed), skipped_devices=sorted(skipped), rejected_actions=rejected,
        )


def _rejected_by_contract(error: HubError) -> bool:
    """Hub odrzucił samo polecenie (np. device_not_found), a nie zawiódł jako usługa."""
    if isinstance(error, HubAuthError) or error.status_code is None or not error.code:
        return False
    return 400 <= error.status_code < 500

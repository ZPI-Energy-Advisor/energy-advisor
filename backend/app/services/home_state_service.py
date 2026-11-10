"""Stan domu Smart Home dla właściciela: zegar i urządzenia z huba, zużycie i koszt bieżącej doby ze zdarzeń.

Zużycie liczymy ze zdarzeń energy_report, a nie z liczników huba: restart mikroserwisu zeruje licznik,
a zdarzenia zostają w bazie. Bierzemy tylko bieżący przebieg symulacji (`simulation_id`), bo ustawienie
zegara zaczyna nowy przebieg i ta sama doba może się powtórzyć.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException, status

from app.clients.hub_client import HubClient, HubError
from app.models.User import User
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.home_event_repository import EnergyStep, HomeEventRepository
from app.repositories.home_repository import HomeRepository
from app.schemas.smart_home import (
    HomeClockState,
    HomeDeviceState,
    HomeEnergyToday,
    HomePower,
    HomeState,
    HubClock,
    HubDevicesStatus,
)
from app.services.schedule_prices import SchedulePriceService


logger = logging.getLogger(__name__)

SLOT = timedelta(minutes=15)
SLOT_SECONDS = SLOT.total_seconds()
NOT_CONNECTED_MESSAGE = "Dom nie jest podłączony. Podłącz dom, żeby zobaczyć jego stan."



@dataclass
class DayEnergy:
    """Energia doby: bilans domu w kwadransach (początek w UTC) i suma na urządzenie, w kWh."""

    by_slot: dict[datetime, float] = field(default_factory=lambda: defaultdict(float))
    by_device: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    consumption_kwh: float = 0.0
    production_kwh: float = 0.0


def _slot_start(moment: datetime) -> datetime:
    timestamp = moment.timestamp()
    return datetime.fromtimestamp(timestamp - timestamp % SLOT_SECONDS, tz=timezone.utc)


def day_energy(steps: list[EnergyStep], start: datetime, end: datetime) -> DayEnergy:
    """Rozkłada energię kroków na kwadranse przedziału [start, end).

    Krok huba to zwykle jeden kwadrans. Dłuższy (urządzenie pominęło tick) dzielimy równo w czasie,
    a część spoza przedziału, np. sprzed północy, nie wchodzi do doby.
    """
    energy = DayEnergy()
    for step in steps:
        span = (step.interval_end - step.interval_start).total_seconds()
        if span <= 0:
            continue
        slot = _slot_start(step.interval_start)
        while slot < step.interval_end:
            overlap = min(slot + SLOT, step.interval_end, end) - max(slot, step.interval_start, start)
            if overlap > timedelta(0):
                share = step.energy_kwh * overlap.total_seconds() / span
                energy.by_slot[slot] += share
                energy.by_device[step.device_id] += share
                if share > 0:
                    energy.consumption_kwh += share
                else:
                    energy.production_kwh -= share
            slot += SLOT
    return energy


def day_start(moment: datetime) -> datetime:
    """Północ doby symulacji w strefie domu (doba ze zmianą czasu ma 23 albo 25 godzin)."""
    return datetime.combine(moment.astimezone(LOCAL_TIMEZONE).date(), time(0), tzinfo=LOCAL_TIMEZONE)


def _kwh(value: float) -> float:
    return round(value, 6) + 0.0  # + 0.0 zamienia -0.0 na 0.0


class HomeStateService:
    def __init__(
        self,
        home_repository: HomeRepository,
        event_repository: HomeEventRepository,
        hub_client: HubClient | None,
        price_service: SchedulePriceService,
    ):
        self.home_repository = home_repository
        self.event_repository = event_repository
        self.hub_client = hub_client
        self.price_service = price_service

    def state(self, owner: User) -> HomeState:
        if self.home_repository.get().user_id != owner.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_CONNECTED_MESSAGE)

        clock, devices = self._read_hub()
        simulation_id = clock.simulation_id if clock else None
        now = clock.sim_time if clock else None
        if simulation_id is None:
            # Hub niedostępny: ostatni znany przebieg i czas z jego zdarzeń.
            position = self.event_repository.latest_position(owner.id)
            if position is not None:
                simulation_id, now = position.simulation_id, now or position.sim_time

        energy = None
        today = None
        if simulation_id is not None:
            now = now.astimezone(LOCAL_TIMEZONE)  # Baza zwraca czas w UTC, a odpowiedź podaje go w strefie domu.
            start = day_start(now)
            steps = self.event_repository.energy_steps(owner.id, simulation_id, start, now)
            energy = day_energy(steps, start, now)
            today = self._today(owner, energy, start, now)

        return HomeState(
            hub_available=clock is not None,
            simulation_id=simulation_id,
            clock=HomeClockState(sim_time=clock.sim_time, running=clock.running, speed=clock.speed) if clock else None,
            power=self._power(devices) if devices else None,
            devices=self._devices(devices, energy) if devices else [],
            today=today,
        )

    def _read_hub(self) -> tuple[HubClock | None, HubDevicesStatus | None]:
        if self.hub_client is None:
            return None, None
        try:
            return self.hub_client.get_clock(), self.hub_client.get_devices()
        except HubError as error:
            logger.warning("Stan domu bez huba: %s", error)
            return None, None

    def _today(self, owner: User, energy: DayEnergy, start: datetime, now: datetime) -> HomeEnergyToday:
        grid_import = {slot: kwh for slot, kwh in energy.by_slot.items() if kwh > 0}
        cost, cost_error = self._cost(owner, grid_import)
        return HomeEnergyToday(
            day_start=start,
            until=now,
            consumption_kwh=_kwh(energy.consumption_kwh),
            production_kwh=_kwh(energy.production_kwh),
            net_kwh=_kwh(sum(energy.by_slot.values())),
            grid_import_kwh=_kwh(sum(grid_import.values())),
            cost_pln=cost,
            cost_error=cost_error,
        )

    def _cost(self, owner: User, grid_import: dict[datetime, float]) -> tuple[float | None, str | None]:
        """Koszt zmienny energii pobranej z sieci: kWh kwadransu razy cena kwadransu taryfy z profilu.

        Bilans liczymy w kwadransie, bo produkcja PV w tym samym kwadransie pokrywa zużycie domu.
        Pomijamy opłaty stałe i wartość energii oddanej do sieci: rozlicza je rachunek okresu, nie doba.
        """
        if not grid_import:
            return 0.0, None
        first, last = min(grid_import), max(grid_import)
        try:
            prices = self.price_service.for_user(owner.id, first, last + SLOT).prices
        except HTTPException as error:  # Niepełny profil albo brak stawek taryfy operatora.
            return None, str(error.detail)
        except ValueError as error:  # Niekompletny cennik w bazie, np. taryfa bez godzin stref dla tego dnia.
            logger.warning("Brak kosztu doby dla domu: %s", error)
            return None, str(error)
        missing = [slot for slot in grid_import if slot not in prices]
        if missing:
            return None, f"Brak cen energii dla {len(missing)} kwadransów doby, np. bez cen rynkowych RCE."
        return round(sum(kwh * prices[slot] for slot, kwh in grid_import.items()), 4), None

    @staticmethod
    def _power(devices: HubDevicesStatus) -> HomePower:
        readings = [device.power_kw for device in devices.devices if device.power_kw is not None]
        return HomePower(
            consumption_kw=_kwh(sum(power for power in readings if power > 0)),
            production_kw=_kwh(-sum(power for power in readings if power < 0)),
            net_kw=_kwh(sum(readings)),
        )

    @staticmethod
    def _devices(devices: HubDevicesStatus, energy: DayEnergy | None) -> list[HomeDeviceState]:
        return [
            HomeDeviceState(
                device_id=device.device_id,
                device_name=device.device_name,
                state=device.state,
                program_id=device.program_id,
                program_started_at=device.program_started_at,
                program_ends_at=device.program_ends_at,
                power_kw=device.power_kw,
                energy_today_kwh=_kwh(energy.by_device.get(device.device_id, 0.0)) if energy else 0.0,
            )
            for device in devices.devices
        ]

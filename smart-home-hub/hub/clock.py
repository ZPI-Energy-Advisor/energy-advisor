import asyncio
import contextlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo



SIM_TIMEZONE = ZoneInfo("Europe/Warsaw")
TICK_STEP = timedelta(minutes=15)
DEFAULT_SPEED = 288.0  # Doba w 5 minut.


class SimClock:
    """Czas symulacji domu, płynie krokami po kwadransie.

    Czas jest trzymany i przesuwany w UTC, więc doba ze zmianą czasu ma 92 albo 100 kwadransów.
    Strefa służy tylko do formatowania, także przesunięcia wysyłanego w tickach.
    """

    def __init__(self):
        midnight = datetime.now(SIM_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        self._now = midnight.astimezone(timezone.utc)
        self.simulation_id = self._new_simulation_id()
        self.running = False
        self.speed = DEFAULT_SPEED
        # Chwila, w której zegar sam staje (np. koniec planu dnia); None: chodzi, dopóki nikt go nie zatrzyma.
        self._stop_at: datetime | None = None
        self._step_left = TICK_STEP.total_seconds()
        self._changed = asyncio.Event()

    @property
    def sim_time(self) -> datetime:
        return self._now.astimezone(SIM_TIMEZONE)

    @property
    def next_time(self) -> datetime:
        return (self._now + TICK_STEP).astimezone(SIM_TIMEZONE)

    @property
    def stop_at(self) -> datetime | None:
        return self._stop_at.astimezone(SIM_TIMEZONE) if self._stop_at else None

    def is_at(self, moment: datetime) -> bool:
        """Porównuje w UTC: między strefami Python uznaje godzinę powtórzoną przy zmianie czasu za różną."""
        return moment.astimezone(timezone.utc) == self._now

    def state(self) -> dict:
        return {
            "sim_time": self.sim_time.isoformat(),
            "running": self.running,
            "speed": self.speed,
            "stop_at": self.stop_at.isoformat() if self.stop_at else None,
            "simulation_id": self.simulation_id,
        }

    def set_time(self, sim_time: datetime) -> None:
        """Zaczyna nowy przebieg symulacji od `sim_time`."""
        self._now = sim_time.astimezone(timezone.utc)
        self.simulation_id = self._new_simulation_id()
        self._stop_at = None  # Zatrzymanie należało do poprzedniego przebiegu.
        self._step_left = TICK_STEP.total_seconds()
        self._changed.set()

    def configure(self, running: bool | None, speed: float | None) -> None:
        if running is not None:
            self.running = running
        if speed is not None:
            self.speed = speed
        self._changed.set()

    def set_stop_at(self, stop_at: datetime | None) -> None:
        self._stop_at = stop_at.astimezone(timezone.utc) if stop_at else None

    def advance(self) -> None:
        """Kwadrans do przodu; zegar staje, gdy dojdzie do `stop_at`, a samo zatrzymanie znika."""
        self._now += TICK_STEP
        if self._stop_at is not None and self._now >= self._stop_at:
            self.running = False
            self._stop_at = None
            self._changed.set()

    def spend(self, seconds: float) -> None:
        """Wlicza czas ticka w kolejny krok. Zaległości nie rosną, gdy ticki trwają dłużej niż krok."""
        self._step_left = max(self._step_left - seconds * self.speed, 0.0)

    async def wait_for_step(self) -> None:
        """Czeka na odmierzenie kroku. Rozpoczęty krok przeżywa pauzę i zmianę tempa."""
        while True:
            self._changed.clear()
            if not self.running:
                await self._changed.wait()
                continue
            if self._step_left <= 0:
                break
            speed = self.speed
            started = time.monotonic()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), self._step_left / speed)
            self._step_left -= (time.monotonic() - started) * speed
        self._step_left = TICK_STEP.total_seconds()
        await asyncio.sleep(0)  # Przy kroku krótszym niż tick pętla nie może zagłodzić serwera.

    @staticmethod
    def _new_simulation_id() -> str:
        return f"sim_{uuid.uuid4().hex}"

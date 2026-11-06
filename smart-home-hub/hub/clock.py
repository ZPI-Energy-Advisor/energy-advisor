import asyncio
import contextlib
import time
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
        self.running = False
        self.speed = DEFAULT_SPEED
        self._step_left = TICK_STEP.total_seconds()
        self._changed = asyncio.Event()

    @property
    def sim_time(self) -> datetime:
        return self._now.astimezone(SIM_TIMEZONE)

    @property
    def next_time(self) -> datetime:
        return (self._now + TICK_STEP).astimezone(SIM_TIMEZONE)

    def state(self) -> dict:
        return {"sim_time": self.sim_time.isoformat(), "running": self.running, "speed": self.speed}

    def set_time(self, sim_time: datetime) -> None:
        self._now = sim_time.astimezone(timezone.utc)
        self._step_left = TICK_STEP.total_seconds()
        self._changed.set()

    def configure(self, running: bool | None, speed: float | None) -> None:
        if running is not None:
            self.running = running
        if speed is not None:
            self.speed = speed
        self._changed.set()

    def advance(self) -> None:
        self._now += TICK_STEP

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

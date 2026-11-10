from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.HomeEvent import HomeEvent
from app.schemas.smart_home import HubEvent



@dataclass(frozen=True)
class EnergyStep:
    device_id: str
    interval_start: datetime
    interval_end: datetime
    energy_kwh: float


@dataclass(frozen=True)
class SimulationPosition:
    simulation_id: str
    sim_time: datetime


class HomeEventRepository:
    """Zdarzenia z webhooka huba w tabeli home_events."""

    def __init__(self, db: Session):
        self.db = db

    def insert_new(self, user_id: UUID | None, events: list[HubEvent]) -> int:
        if not events:
            return 0
        rows = []
        for event in events:
            report = event.energy_report
            rows.append({
                "event_id": event.event_id,
                "user_id": user_id,
                "simulation_id": event.simulation_id,
                "type": event.type,
                "device_id": event.device_id,
                "sim_time": event.sim_time,
                "interval_start": report.interval_start if report else None,
                "energy_kwh": report.energy_kwh if report else None,
                "data": event.data,
            })
        statement = (
            insert(HomeEvent)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[HomeEvent.event_id])
            .returning(HomeEvent.id)
        )
        return len(self.db.execute(statement).all())

    def energy_steps(
        self, user_id: UUID, simulation_id: str, start: datetime, end: datetime,
    ) -> list[EnergyStep]:
        """Kroki energy_report przebiegu, które zachodzą na przedział [start, end)."""
        rows = self.db.execute(
            select(HomeEvent.device_id, HomeEvent.interval_start, HomeEvent.sim_time, HomeEvent.energy_kwh)
            .where(
                HomeEvent.user_id == user_id,
                HomeEvent.simulation_id == simulation_id,
                HomeEvent.type == HomeEvent.ENERGY_REPORT,
                HomeEvent.sim_time > start,
                HomeEvent.interval_start < end,
            )
        ).all()
        return [EnergyStep(*row) for row in rows]

    def latest_position(self, user_id: UUID) -> SimulationPosition | None:
        """Przebieg z ostatnio odebranego zdarzenia i najpóźniejszy czas symulacji w nim (gdy hub nie odpowiada)."""
        simulation_id = self.db.execute(
            select(HomeEvent.simulation_id)
            .where(HomeEvent.user_id == user_id)
            .order_by(HomeEvent.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if simulation_id is None:
            return None
        sim_time = self.db.execute(
            select(func.max(HomeEvent.sim_time))
            .where(HomeEvent.user_id == user_id, HomeEvent.simulation_id == simulation_id)
        ).scalar_one()
        return SimulationPosition(simulation_id, sim_time)

    def commit(self) -> None:
        self.db.commit()

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.PlanRun import PlanRun


class PlanRunRepository:
    """Przebiegi planu dnia w symulacji"""

    def __init__(self, db: Session):
        self.db = db

    def add(self, run: PlanRun) -> PlanRun:
        self.db.add(run)
        self.db.flush()
        return run

    def latest(self, user_id: UUID) -> PlanRun | None:
        return self.db.execute(
            select(PlanRun).where(PlanRun.user_id == user_id).order_by(PlanRun.started_at.desc()).limit(1)
        ).scalar_one_or_none()

    def latest_runs(self, user_id: UUID, limit: int) -> list[PlanRun]:
        return list(self.db.execute(
            select(PlanRun).where(PlanRun.user_id == user_id).order_by(PlanRun.started_at.desc()).limit(limit)
        ).scalars())

    def get(self, user_id: UUID, run_id: UUID) -> PlanRun | None:
        return self.db.execute(
            select(PlanRun).where(PlanRun.id == run_id, PlanRun.user_id == user_id)
        ).scalar_one_or_none()

    def for_simulation(self, user_id: UUID, simulation_id: str) -> PlanRun | None:
        """Najnowszy przebieg planu danej symulacji huba (każdy przebieg zaczyna własną symulację)."""
        return self.db.execute(
            select(PlanRun)
            .where(PlanRun.user_id == user_id, PlanRun.simulation_id == simulation_id)
            .order_by(PlanRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def running(self, user_id: UUID) -> list[PlanRun]:
        return list(self.db.execute(
            select(PlanRun).where(PlanRun.user_id == user_id, PlanRun.status == PlanRun.RUNNING)
        ).scalars())

    def commit(self) -> None:
        self.db.commit()

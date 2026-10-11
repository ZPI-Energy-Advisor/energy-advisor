from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.PriceSyncRun import PriceSyncRun, PriceSyncStatus



class PriceSyncRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def start(self, source: str, trigger: str, date_from: date, date_to: date, days_requested: int, started_at: datetime) -> PriceSyncRun:
        run = PriceSyncRun(
            source=source,
            trigger=trigger,
            status=PriceSyncStatus.RUNNING,
            date_from=date_from,
            date_to=date_to,
            days_requested=days_requested,
            started_at=started_at,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def finish(
        self,
        run: PriceSyncRun,
        status: str,
        days_synced: int,
        records_upserted: int,
        error_message: str | None,
        finished_at: datetime,
    ) -> PriceSyncRun:
        run.status = status
        run.days_synced = days_synced
        run.records_upserted = records_upserted
        run.error_message = error_message
        run.finished_at = finished_at
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_latest(self, source: str) -> PriceSyncRun | None:
        return (
            self.db.query(PriceSyncRun)
            .filter(PriceSyncRun.source == source)
            .order_by(PriceSyncRun.started_at.desc(), PriceSyncRun.id.desc())
            .first()
        )

    def get_latest_with_status(self, source: str, status: str) -> PriceSyncRun | None:
        return (
            self.db.query(PriceSyncRun)
            .filter(PriceSyncRun.source == source, PriceSyncRun.status == status)
            .order_by(PriceSyncRun.started_at.desc(), PriceSyncRun.id.desc())
            .first()
        )

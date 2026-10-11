from sqlalchemy import Column, Date, DateTime, Index, Integer, String, Text

from app.database import Base



class PriceSyncStatus:
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    NO_DATA = "no_data"
    FAILED = "failed"


class PriceSyncTrigger:
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    CLI = "cli"


class PriceSyncRun(Base):
    __tablename__ = "price_sync_runs"
    __table_args__ = (Index("ix_price_sync_runs_source_started_at", "source", "started_at"),)

    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False)
    trigger = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)

    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    days_requested = Column(Integer, nullable=False, default=0)
    days_synced = Column(Integer, nullable=False, default=0)
    records_upserted = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

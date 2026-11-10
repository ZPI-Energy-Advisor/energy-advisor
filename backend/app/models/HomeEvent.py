from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base



class HomeEvent(Base):
    """Zdarzenie urządzenia z webhooka huba (device_started, device_finished, energy_report, device_error).

    `event_id` nadaje hub i jest unikalny: ponowiona partia nie dubluje zdarzeń, a więc i energii.
    Zużycie domu to suma `energy_kwh` zdarzeń energy_report jednego przebiegu symulacji (`simulation_id`);
    energia w device_finished opisuje tylko cykl i zostaje w `data`.
    """

    __tablename__ = "home_events"
    __table_args__ = (
        CheckConstraint(
            "(type = 'energy_report') = (energy_kwh IS NOT NULL AND interval_start IS NOT NULL)",
            name="ck_home_events_energy_report",
        ),
        Index("ix_home_events_energy", "simulation_id", "sim_time", postgresql_where="type = 'energy_report'"),
        Index("ix_home_events_user_received", "user_id", "id"),
    )

    ENERGY_REPORT = "energy_report"

    id = Column(BigInteger, primary_key=True)
    event_id = Column(String(64), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    simulation_id = Column(String(64), nullable=False)
    type = Column(String(32), nullable=False)
    device_id = Column(String(100), nullable=False)
    sim_time = Column(DateTime(timezone=True), nullable=False)
    interval_start = Column(DateTime(timezone=True), nullable=True)
    energy_kwh = Column(Float, nullable=True)
    data = Column(JSONB, nullable=False, default=dict)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

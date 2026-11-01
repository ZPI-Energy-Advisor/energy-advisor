from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class DeviceSlotUsage(Base):
    """Rozkład akcji na kwadranse, do szybkich agregacji (wycena, wykresy, podział na kategorie)."""

    __tablename__ = "device_slot_usage"
    __table_args__ = (
        Index("ix_device_slot_usage_file_slot", "energy_data_file_id", "slot_start"),
    )

    device_action_id = Column(
        BigInteger,
        ForeignKey("device_actions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    slot_start = Column(DateTime(timezone=True), primary_key=True)
    # Kopia z device_instances: sumy zużycia pliku w kwadransach liczymy bez złączeń.
    energy_data_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("energy_data_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    kwh = Column(Float, nullable=False)

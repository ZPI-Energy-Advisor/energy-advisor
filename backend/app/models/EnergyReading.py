from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class EnergyReading(Base):
    __tablename__ = "energy_readings"
    __table_args__ = (
        UniqueConstraint(
            "energy_data_file_id",
            "measured_at",
            name="uq_energy_reading_file_timestamp",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    energy_data_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("energy_data_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    measured_at = Column(DateTime, nullable=False)
    energy_kwh = Column(Numeric(12, 6), nullable=False)

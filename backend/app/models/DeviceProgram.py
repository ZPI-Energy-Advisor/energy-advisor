from sqlalchemy import BigInteger, Column, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from app.database import Base



class DeviceProgram(Base):
    """Program urządzenia (np. "Bawełna 60°C"): kształt cyklu, który optymalizacja przesuwa razem z akcją."""

    __tablename__ = "device_programs"
    __table_args__ = (
        UniqueConstraint("device_instance_id", "source_program_id", name="uq_device_program_instance_program"),
    )

    id = Column(BigInteger, primary_key=True)
    device_instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("device_instances.id", ondelete="CASCADE"),
        nullable=False,
    )

    # program_id z pliku (np. "cotton_60"), unikalny w obrębie urządzenia.
    source_program_id = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    duration_min = Column(Integer, nullable=False)
    # Energia w kolejnych kwadransach cyklu (kWh), duration_min / 15 wartości.
    profile_kwh = Column(ARRAY(Float), nullable=False)

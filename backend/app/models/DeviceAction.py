from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class DeviceAction(Base):
    """Akcja z energy_usage: jednostka, którą optymalizacja przesuwa, a symulacja uruchamia."""

    __tablename__ = "device_actions"
    __table_args__ = (
        UniqueConstraint("device_instance_id", "source_action_id", name="uq_device_action_instance_action"),
        CheckConstraint("action_start < action_end", name="ck_device_action_start_before_end"),
    )

    id = Column(BigInteger, primary_key=True)
    device_instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("device_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_program_id = Column(
        BigInteger,
        ForeignKey("device_programs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # action_id z pliku (np. "act_0016").
    source_action_id = Column(String(100), nullable=False)
    # Czasy jako timestamptz w UTC - jednoznaczne także w dniach zmiany czasu.
    action_start = Column(DateTime(timezone=True), nullable=False)
    action_end = Column(DateTime(timezone=True), nullable=False)
    # Ujemna energia oznacza produkcję (kategoria OZE).
    energy_kwh = Column(Float, nullable=False)

    # Sesja ładowania EV: okno, w którym optymalizacja może rozłożyć energię.
    plugged_in = Column(DateTime(timezone=True), nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class DeviceAction(Base):
    """Akcja z energy_usage: jednostka, którą optymalizacja przesuwa, a symulacja uruchamia.

    Urządzenie należy do domu, a akcja do pliku: usunięcie pliku usuwa jego akcje.
    """

    __tablename__ = "device_actions"
    __table_args__ = (
        # action_id jest unikalne w pliku; kolejne pliki tego samego domu mogą powtarzać numerację.
        UniqueConstraint("energy_data_file_id", "source_action_id", name="uq_device_action_file_action"),
        CheckConstraint("action_start < action_end", name="ck_device_action_start_before_end"),
    )

    id = Column(BigInteger, primary_key=True)
    device_instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("device_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Indeks na energy_data_file_id zapewnia ograniczenie unikalności (energy_data_file_id, source_action_id).
    energy_data_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("energy_data_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Akcja jest faktem z historii zużycia, więc przeżywa usunięcie programu.
    device_program_id = Column(
        BigInteger,
        ForeignKey("device_programs.id", ondelete="SET NULL"),
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

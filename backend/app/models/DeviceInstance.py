import uuid

from sqlalchemy import CheckConstraint, Column, Float, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class DeviceInstance(Base):
    """Urządzenie w domu użytkownika: jedno na device_id, niezależnie od liczby wgranych plików.

    Import aktualizuje urządzenie po device_id (najnowszy plik wygrywa). Pliki, w których urządzenie
    występuje, wskazuje DeviceInstanceFile; usunięcie ostatniego takiego pliku usuwa urządzenie.
    """

    __tablename__ = "device_instances"
    __table_args__ = (
        UniqueConstraint("user_id", "source_device_id", name="uq_device_instance_user_device"),
        CheckConstraint(
            "flexibility_mode IN ('fixed', 'shiftable', 'interruptible')",
            name="ck_device_instance_flexibility_mode",
        ),
    )

    FIXED = "fixed"
    SHIFTABLE = "shiftable"
    INTERRUPTIBLE = "interruptible"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Indeks na user_id zapewnia ograniczenie unikalności (user_id, source_device_id).
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # device_id z pliku (np. "dev_wm_01"); id to klucz w bazie.
    source_device_id = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    # Kategoria jest cechą urządzenia, nie typu: rekuperator bywa "Ogrzewanie", odkurzacz "Inne".
    device_type = Column(String(40), ForeignKey("device_types.code"), nullable=False)
    device_category = Column(String(40), ForeignKey("device_categories.code"), nullable=False)
    max_power_kw = Column(Float, nullable=True)

    # Obiekt flexibility z pliku. Godziny okna są czasem lokalnym (Europe/Warsaw), okno może przechodzić przez północ.
    flexibility_mode = Column(String(20), nullable=False)
    allowed_window_from = Column(Time, nullable=True)
    allowed_window_to = Column(Time, nullable=True)
    max_shift_min = Column(Integer, nullable=True)

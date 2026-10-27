import uuid

from sqlalchemy import CheckConstraint, Column, Float, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class DeviceInstance(Base):
    """Urządzenie z pliku urządzeń. Każdy import zapisuje własny komplet urządzeń."""

    __tablename__ = "device_instances"
    __table_args__ = (
        UniqueConstraint("energy_data_file_id", "source_device_id", name="uq_device_instance_file_device"),
        CheckConstraint(
            "flexibility_mode IN ('fixed', 'shiftable', 'interruptible')",
            name="ck_device_instance_flexibility_mode",
        ),
    )

    FIXED = "fixed"
    SHIFTABLE = "shiftable"
    INTERRUPTIBLE = "interruptible"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    energy_data_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("energy_data_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

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

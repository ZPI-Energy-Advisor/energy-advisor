from sqlalchemy import Column, String

from app.database import Base



class DeviceType(Base):
    """Słownik typów urządzeń z docs/devices-file-format.md, seedowany w migracji."""

    __tablename__ = "device_types"

    code = Column(String(40), primary_key=True)
    label = Column(String(80), nullable=False)

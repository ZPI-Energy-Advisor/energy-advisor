from sqlalchemy import Column, String

from app.database import Base



class DeviceCategory(Base):
    """Słownik kategorii urządzeń z docs/devices-file-format.md, seedowany w migracji."""

    __tablename__ = "device_categories"

    # Kod jest wartością device_category z pliku (np. "RTV/IT") i od razu nazwą w UI.
    code = Column(String(40), primary_key=True)

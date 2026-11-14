from sqlalchemy import Column, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base



class PlanningTemplate(Base):
    """Ustawienia planu na jutro użytkownika (ZP-111): wymagania urządzeń z jego plików.

    Jeden zestaw na konto, nadpisywany przy każdym zapisie. `devices` to lista preferencji urządzeń
    w kształcie `DevicePreference` (schemas/planning.py), według `device_id` z pliku urządzeń, także
    pojemność baterii auta, którą użytkownik podaje raz.
    """

    __tablename__ = "planning_templates"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    devices = Column(JSONB, nullable=False, default=list)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

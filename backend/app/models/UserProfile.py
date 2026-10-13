from sqlalchemy import Column, Enum, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.schemas.user_profile import PropertyTypeEnum


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    type_of_property = Column(Enum(PropertyTypeEnum, name="property_type"), nullable=False)
    heating_area_m2 = Column(Float, nullable=False)
    place_latitude = Column(Float, nullable=True)
    place_longitude = Column(Float, nullable=True)
    number_of_residents = Column(Integer, nullable=False)
    current_tariff_id = Column(
        Integer,
        ForeignKey("tariffs.id", ondelete="SET NULL"),
        nullable=True,
    )
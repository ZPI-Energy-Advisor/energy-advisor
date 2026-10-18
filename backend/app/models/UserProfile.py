from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base



class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),primary_key=True, nullable=False)
    base_info = Column(JSONB, nullable=False)
    consumption_and_tariff = Column(JSONB, nullable=False)
    pv_config = Column(JSONB, nullable=False)
    commercial_offer = Column(JSONB, nullable=True)
    distribution_fees = Column(JSONB, nullable=False)
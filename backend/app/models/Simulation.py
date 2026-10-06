import datetime
import uuid
from sqlalchemy import Column, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.database import Base



class Simulation(Base):
    __tablename__ = "simulations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    results = Column(JSONB, nullable=False)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
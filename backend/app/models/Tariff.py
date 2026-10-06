from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base



class Tariff(Base):
    __tablename__ = "tariffs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    
    rates = relationship("TariffRate", back_populates="tariff", cascade="all, delete-orphan")

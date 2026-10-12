from sqlalchemy import Column, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base



class Tariff(Base):
    __tablename__ = "tariffs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)

    markup_pln_kwh = Column(Numeric(10, 4), nullable=True)
    vat_rate = Column(Numeric(5, 4), nullable=True)
    
    rates = relationship("TariffRate", back_populates="tariff", cascade="all, delete-orphan")

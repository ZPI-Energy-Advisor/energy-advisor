from sqlalchemy import Column, Integer, ForeignKey, Time, DECIMAL
from sqlalchemy.orm import relationship

from app.database import Base



class TariffRate(Base):
    __tablename__ = "tariff_rates"
    id = Column(Integer, primary_key=True, index=True)
    tariff_id = Column(Integer, ForeignKey("tariffs.id", ondelete="CASCADE"), nullable=False)
    
    time_start = Column(Time, nullable=False)
    time_end = Column(Time, nullable=False)
    
    price_per_kwh = Column(DECIMAL(10, 4), nullable=False)
    
    tariff = relationship("Tariff", back_populates="rates")
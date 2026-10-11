from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)

from app.database import Base



class DynamicPriceObservation(Base):
    __tablename__ = "dynamic_price_observations"
    __table_args__ = (
        UniqueConstraint("source", "interval_start", name="uq_dynamic_price_source_interval"),
        Index("ix_dynamic_price_source_business_date", "source", "business_date"),
    )

    id = Column(BigInteger, primary_key=True)
    source = Column(String(50), nullable=False)

    # Początek interwału jako timestamptz w UTC - jednoznaczny także w dniach zmiany czasu.
    interval_start = Column(DateTime(timezone=True), nullable=False)
    interval_minutes = Column(SmallInteger, nullable=False)
    # Doba handlowa w czasie lokalnym (Europe/Warsaw), do której dostawca przypisał cenę.
    business_date = Column(Date, nullable=False)

    # Cena w jednostce źródła: PLN/MWh, netto, może być ujemna.
    price_pln_mwh = Column(Numeric(12, 4), nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

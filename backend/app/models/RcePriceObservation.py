from sqlalchemy import BigInteger, Column, Date, DateTime, Index, Identity, Numeric, SmallInteger, String, UniqueConstraint, func

from app.database import Base



class RcePriceObservation(Base):
    __tablename__ = "rce_price_observations"
    __table_args__ = (
        UniqueConstraint("source", "interval_start", name="uq_rce_price_source_interval"),
        Index("ix_rce_price_source_business_date", "source", "business_date"),
    )

    id = Column(BigInteger, Identity(), primary_key=True)
    source = Column(String(50), nullable=False)
    interval_start = Column(DateTime(timezone=True), nullable=False)
    interval_minutes = Column(SmallInteger, nullable=False)
    business_date = Column(Date, nullable=False)
    price_pln_mwh = Column(Numeric(12, 4), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

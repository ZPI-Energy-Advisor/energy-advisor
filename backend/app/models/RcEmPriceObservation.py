from sqlalchemy import BigInteger, Column, Date, DateTime, Identity, Index, Numeric, String, UniqueConstraint, func

from app.database import Base



class RcEmPriceObservation(Base):
    __tablename__ = "rcem_price_observations"
    __table_args__ = (
        UniqueConstraint("source", "price_month", name="uq_rcem_price_source_month"),
        Index("ix_rcem_price_source_month", "source", "price_month"),
    )

    id = Column(BigInteger, Identity(), primary_key=True)
    source = Column(String(50), nullable=False)
    price_month = Column(Date, nullable=False)
    price_pln_mwh = Column(Numeric(12, 4), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

from sqlalchemy import BigInteger, Column, DateTime, Identity, Index, Numeric, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint("latitude", "longitude", "source", "interval_start", name="uq_weather_cell_source_interval"),
        Index("ix_weather_cell_interval", "latitude", "longitude", "interval_start"),
    )

    SOURCE_FORECAST = "forecast"
    SOURCE_ARCHIVE = "archive"

    id = Column(BigInteger, Identity(), primary_key=True)
    latitude = Column(Numeric(4, 1), nullable=False)
    longitude = Column(Numeric(4, 1), nullable=False)
    source = Column(String(20), nullable=False)
    interval_start = Column(DateTime(timezone=True), nullable=False)
    interval_minutes = Column(SmallInteger, nullable=False)
    temperature_c = Column(Numeric(5, 2), nullable=True)
    cloud_cover_pct = Column(SmallInteger, nullable=True)
    ghi_w_m2 = Column(Numeric(7, 2), nullable=True)
    tilted_w_m2 = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    fetched_at = Column(DateTime(timezone=True), nullable=False)

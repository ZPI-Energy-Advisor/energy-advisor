from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from app.models.WeatherObservation import WeatherObservation
from app.providers.weather import WeatherPoint

INSERT_CHUNK_ROWS = 2000


class WeatherRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        latitude: Decimal,
        longitude: Decimal,
        source: str,
        points: Sequence[WeatherPoint],
        fetched_at: datetime,
    ) -> int:
        rows = [
            {
                "latitude": latitude,
                "longitude": longitude,
                "source": source,
                "interval_start": point.interval_start,
                "interval_minutes": point.interval_minutes,
                "temperature_c": point.temperature_c,
                "cloud_cover_pct": point.cloud_cover_pct,
                "ghi_w_m2": point.ghi_w_m2,
                "tilted_w_m2": point.tilted,
                "fetched_at": fetched_at,
            }
            for point in points
        ]
        try:
            for offset in range(0, len(rows), INSERT_CHUNK_ROWS):
                statement = insert(WeatherObservation).values(rows[offset:offset + INSERT_CHUNK_ROWS])
                excluded = statement.excluded
                statement = statement.on_conflict_do_update(
                    constraint="uq_weather_cell_source_interval",
                    set_={
                        "interval_minutes": excluded.interval_minutes,
                        "temperature_c": func.coalesce(excluded.temperature_c, WeatherObservation.temperature_c),
                        "cloud_cover_pct": func.coalesce(excluded.cloud_cover_pct, WeatherObservation.cloud_cover_pct),
                        "ghi_w_m2": func.coalesce(excluded.ghi_w_m2, WeatherObservation.ghi_w_m2),
                        "tilted_w_m2": WeatherObservation.tilted_w_m2.op("||", return_type=JSONB)(excluded.tilted_w_m2),
                        "fetched_at": excluded.fetched_at,
                    },
                )
                self.db.execute(statement)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return len(rows)

    def between(self, latitude: Decimal, longitude: Decimal, start: datetime, end: datetime) -> list[WeatherObservation]:
        return (
            self.db.query(WeatherObservation)
            .filter(
                WeatherObservation.latitude == latitude,
                WeatherObservation.longitude == longitude,
                WeatherObservation.interval_start >= start,
                WeatherObservation.interval_start < end,
            )
            .order_by(WeatherObservation.interval_start)
            .all()
        )

    def delete_forecasts_before(self, moment: datetime) -> int:
        try:
            deleted = (
                self.db.query(WeatherObservation)
                .filter(
                    WeatherObservation.source == WeatherObservation.SOURCE_FORECAST,
                    WeatherObservation.interval_start < moment,
                )
                .delete(synchronize_session=False)
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return deleted

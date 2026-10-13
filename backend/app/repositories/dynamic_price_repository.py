from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, literal
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.DynamicPriceObservation import DynamicPriceObservation
from app.providers.prices.base import PricePoint



class DynamicPriceRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_many(self, points: Sequence[PricePoint]) -> int:
        """Zapis idempotentny: ON CONFLICT na (source, interval_start) aktualizuje istniejący wiersz,
        więc ponowny import tego samego okresu nie tworzy duplikatów."""
        if not points:
            return 0

        rows = [
            {
                "source": p.source,
                "interval_start": p.interval_start,
                "interval_minutes": p.interval_minutes,
                "business_date": p.business_date,
                "price_pln_mwh": p.price_pln_mwh,
            }
            for p in points
        ]
        stmt = insert(DynamicPriceObservation).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_dynamic_price_source_interval",
            set_={
                "interval_minutes": stmt.excluded.interval_minutes,
                "business_date": stmt.excluded.business_date,
                "price_pln_mwh": stmt.excluded.price_pln_mwh,
                "updated_at": func.now(),
            },
        )
        try:
            self.db.execute(stmt)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return len(rows)

    def get_for_business_date(self, source: str, business_date: date) -> list[DynamicPriceObservation]:
        return (
            self.db.query(DynamicPriceObservation)
            .filter(
                DynamicPriceObservation.source == source,
                DynamicPriceObservation.business_date == business_date,
            )
            .order_by(DynamicPriceObservation.interval_start)
            .all()
        )

    def get_prices_between(self, source: str, start_utc: datetime, end_utc: datetime) -> dict[datetime, Decimal]:
        rows = (
            self.db.query(DynamicPriceObservation.interval_start, DynamicPriceObservation.price_pln_mwh)
            .filter(
                DynamicPriceObservation.source == source,
                DynamicPriceObservation.interval_start >= start_utc,
                DynamicPriceObservation.interval_start < end_utc,
            )
            .all()
        )
        return {interval_start: price for interval_start, price in rows}

    def count_by_business_date(self, source: str, date_from: date, date_to: date) -> dict[date, int]:
        rows = (
            self.db.query(DynamicPriceObservation.business_date, func.count(DynamicPriceObservation.id))
            .filter(
                DynamicPriceObservation.source == source,
                DynamicPriceObservation.business_date >= date_from,
                DynamicPriceObservation.business_date <= date_to,
            )
            .group_by(DynamicPriceObservation.business_date)
            .all()
        )
        return {business_date: count for business_date, count in rows}

    def get_available_range(self, source: str) -> tuple[date | None, date | None, datetime | None]:
        return (
            self.db.query(
                func.min(DynamicPriceObservation.business_date),
                func.max(DynamicPriceObservation.business_date),
                func.max(DynamicPriceObservation.updated_at),
            )
            .filter(DynamicPriceObservation.source == source)
            .one()
        )

    def get_range_stats(self, source: str, date_from: date, date_to: date) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        return (
            self._in_range(
                self.db.query(
                    func.avg(DynamicPriceObservation.price_pln_mwh),
                    func.min(DynamicPriceObservation.price_pln_mwh),
                    func.max(DynamicPriceObservation.price_pln_mwh),
                ),
                source, date_from, date_to,
            )
            .one()
        )

    def get_quarter_hour_prices(self, source: str, date_from: date, date_to: date) -> list[tuple[datetime, Decimal, int]]:
        return (
            self._in_range(
                self.db.query(
                    DynamicPriceObservation.interval_start,
                    DynamicPriceObservation.price_pln_mwh,
                    literal(1),
                ),
                source, date_from, date_to,
            )
            .order_by(DynamicPriceObservation.interval_start)
            .all()
        )

    def get_hourly_averages(self, source: str, date_from: date, date_to: date) -> list[tuple[datetime, Decimal, int]]:
        hour = func.date_trunc("hour", DynamicPriceObservation.interval_start, "UTC")
        return (
            self._in_range(
                self.db.query(hour, func.avg(DynamicPriceObservation.price_pln_mwh), func.count(DynamicPriceObservation.id)),
                source, date_from, date_to,
            )
            .group_by(hour)
            .order_by(hour)
            .all()
        )

    def get_daily_averages(self, source: str, date_from: date, date_to: date) -> list[tuple[date, Decimal, int]]:
        return (
            self._in_range(
                self.db.query(
                    DynamicPriceObservation.business_date,
                    func.avg(DynamicPriceObservation.price_pln_mwh),
                    func.count(DynamicPriceObservation.id),
                ),
                source, date_from, date_to,
            )
            .group_by(DynamicPriceObservation.business_date)
            .order_by(DynamicPriceObservation.business_date)
            .all()
        )

    @staticmethod
    def _in_range(query, source: str, date_from: date, date_to: date):
        return query.filter(
            DynamicPriceObservation.source == source,
            DynamicPriceObservation.business_date >= date_from,
            DynamicPriceObservation.business_date <= date_to,
        )

from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func
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

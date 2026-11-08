from datetime import date
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.schemas.other import DistributionOperatorEnum
from app.models.NewModels import RegulatoryPeriod, TariffDefinition, UnsupportedTariff



class TariffDefinitionRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _with_rates(query):
        return query.options(
            selectinload(TariffDefinition.variable_network_rates),
            selectinload(TariffDefinition.subscription_fees),
            selectinload(TariffDefinition.supplier_ure_rates),
            selectinload(TariffDefinition.zone_hours),
        )

    def list_for_period(
        self,
        *,
        operator: DistributionOperatorEnum,
        date_from: date,
        date_to: date,
    ) -> list[TariffDefinition]:
        """Definicje operatora ważne choćby przez jeden dzień okresu [date_from, date_to]."""
        return (
            self._with_rates(self.db.query(TariffDefinition))
            .filter(
                TariffDefinition.osd_operator == operator,
                TariffDefinition.valid_from <= date_to,
                TariffDefinition.valid_to >= date_from,
            )
            .order_by(TariffDefinition.tariff_code, TariffDefinition.valid_from)
            .all()
        )

    def list_for_operator(self, *, operator: DistributionOperatorEnum) -> list[TariffDefinition]:
        """Wszystkie definicje operatora (opcje formularza profilu)."""
        return (
            self._with_rates(self.db.query(TariffDefinition))
            .filter(TariffDefinition.osd_operator == operator)
            .order_by(TariffDefinition.tariff_code, TariffDefinition.valid_from)
            .all()
        )

    def first_valid_from(self, *, operator: DistributionOperatorEnum) -> date | None:
        """Pierwszy dzień, od którego operator ma jakiekolwiek stawki w bazie."""
        return (
            self.db.query(func.min(TariffDefinition.valid_from))
            .filter(TariffDefinition.osd_operator == operator)
            .scalar()
        )

    def list_regulatory_periods(self, *, date_from: date, date_to: date) -> list[RegulatoryPeriod]:
        """Okresy opłat regulacyjnych ważne choćby przez jeden dzień okresu [date_from, date_to]."""
        return (
            self.db.query(RegulatoryPeriod)
            .options(
                selectinload(RegulatoryPeriod.capacity_thresholds),
                selectinload(RegulatoryPeriod.transition_thresholds),
            )
            .filter(RegulatoryPeriod.valid_from <= date_to, RegulatoryPeriod.valid_to >= date_from)
            .order_by(RegulatoryPeriod.valid_from)
            .all()
        )

    def list_unsupported(
        self,
        *,
        operator: DistributionOperatorEnum,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[UnsupportedTariff]:
        """Taryfy operatora, których nie liczymy (w okresie albo wszystkie)."""
        query = self.db.query(UnsupportedTariff).filter(UnsupportedTariff.osd_operator == operator)
        if date_from is not None and date_to is not None:
            query = query.filter(UnsupportedTariff.valid_from <= date_to, UnsupportedTariff.valid_to >= date_from)
        return query.order_by(UnsupportedTariff.tariff_code, UnsupportedTariff.valid_from).all()

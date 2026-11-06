from datetime import date
from sqlalchemy.orm import Session, selectinload

from app.schemas.other import TariffTypeEnum, DistributionOperatorEnum
from app.models.NewModels import RegulatoryPeriod, TariffDefinition



class TariffDefinitionRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _with_rates(query):
        return query.options(
            selectinload(TariffDefinition.variable_network_rates),
            selectinload(TariffDefinition.subscription_fees),
            selectinload(TariffDefinition.supplier_ure_rates),
        )

    def get_for_calculation(
        self,
        *,
        operator: DistributionOperatorEnum,
        tariff_code: TariffTypeEnum,
        calculation_date: date,
    ) -> TariffDefinition | None:
        return (
            self._with_rates(self.db.query(TariffDefinition))
            .filter(
                TariffDefinition.osd_operator == operator,
                TariffDefinition.tariff_code == tariff_code,
                TariffDefinition.valid_from <= calculation_date,
                TariffDefinition.valid_to >= calculation_date,
            )
            .first()
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

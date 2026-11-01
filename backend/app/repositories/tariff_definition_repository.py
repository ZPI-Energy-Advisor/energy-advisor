from datetime import date
from sqlalchemy.orm import Session, selectinload

from app.schemas.other import TariffTypeEnum, DistributionOperatorEnum
from app.models.NewModels import  TariffDefinition



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

    def list_for_calculation(
        self,
        *,
        operator: DistributionOperatorEnum,
        calculation_date: date,
    ) -> list[TariffDefinition]:
        return (
            self._with_rates(self.db.query(TariffDefinition))
            .filter(
                TariffDefinition.osd_operator == operator,
                TariffDefinition.valid_from <= calculation_date,
                TariffDefinition.valid_to >= calculation_date,
            )
            .order_by(TariffDefinition.tariff_code)
            .all()
        )

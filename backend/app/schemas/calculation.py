from datetime import date, datetime
from typing import TypeAlias
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.other import (
    BillingCycleEnum,
    DistributionOperatorEnum,
    EnergyTimeSeries,
    PhaseTypeEnum,
    PVTypeEnum,
    TariffTypeEnum,
    TypeOfMarketEnergyEnum,
)




BalancedEnergyCycles: TypeAlias = (
    list[tuple[datetime, list[float]]]
)
CalculationEnergyCycles: TypeAlias = EnergyTimeSeries | BalancedEnergyCycles


class TariffData(BaseModel):
    """User inputs required to select the applicable tariff rates."""

    tariff_type: TariffTypeEnum
    billing_cycle: BillingCycleEnum
    billing_period_start_date: date
    distribution_operator: DistributionOperatorEnum
    phase_type: PhaseTypeEnum
    contracted_power_kw: float = Field(gt=0, le=10000)


class PVDetails(BaseModel):
    """PV inputs and derived values used by the balancing calculation."""

    model_config = ConfigDict(extra="forbid")

    pv_energy_cycles: EnergyTimeSeries
    mode: PVTypeEnum
    power_of_pv_kwp: float | None = Field(default=None, gt=0, le=50)
    type_of_market_energy: TypeOfMarketEnergyEnum | None = None

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "PVDetails":
        if self.mode == PVTypeEnum.NET_METERING and self.power_of_pv_kwp is None:
            raise ValueError("Moc instalacji PV jest wymagana dla net-meteringu.")
        if self.mode == PVTypeEnum.NET_BILLING and self.type_of_market_energy is None:
            raise ValueError("Typ ceny energii jest wymagany dla net-billingu.")
        return self

    @computed_field
    @property
    def k_var(self) -> float | None:
        if self.mode != PVTypeEnum.NET_METERING or self.power_of_pv_kwp is None:
            return None
        return 0.8 if self.power_of_pv_kwp <= 10.0 else 0.7


class AnnualConsumption(BaseModel):
    """Roczne zużycie, od którego zależą progi opłaty mocowej i przejściowej.

    Suma poboru z sieci w pliku przeskalowana do 365 dni: plik krótszy niż rok jest rozszerzany
    proporcjonalnie, dłuższy - uśredniany.
    """

    data_start: date
    data_end: date
    days: int
    consumption_kwh: float
    annual_kwh: float
    scaled: bool


class CalculationDetails(BaseModel):
    pv_details: PVDetails | None = None
    
    used_energy_cycles: CalculationEnergyCycles
    tariff_data: TariffData
    annual_consumption: AnnualConsumption | None = None

    used_energy_after_balancing_cycles: BalancedEnergyCycles | None = None
    overpayment_cycles: list[dict[str, float]] | None = None
    tariff_calculation: dict[str, object] | None = None
    tariff_calculations: dict[str, dict[str, object]] | None = None
    tariff_calculation_errors: dict[str, str] | None = None
    # Uwagi do danych wejściowych, które nie blokują kalkulacji (np. pominięte oddanie energii).
    warnings: list[str] | None = None
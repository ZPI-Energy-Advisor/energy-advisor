from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.schemas.other import (
    BillingCycleEnum,
    DistributionOperatorEnum,
    PhaseTypeEnum,
    PropertyTypeEnum,
    TariffTypeEnum,
    TypeOfMarketEnergyEnum,
)



# ==========================================
# 1. BASE INFO ABOUT BUILDING
# ==========================================

class BaseInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type_of_property: PropertyTypeEnum
    year_of_construction: int = Field(gt=1800, le=2027)
    heating_area_m2: float = Field(gt=0, le=10000)
    number_of_residents: int = Field(gt=0)
    town: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(pattern=r"^\d{2}-\d{3}$", description="Kod pocztowy punktu poboru w Polsce")
    distribution_operator: DistributionOperatorEnum
    phase_type: PhaseTypeEnum
    contracted_power_kw: float = Field(
        gt=0,
        le=10000,
        description="Moc umowna przyłącza w kW; wpływa na opłaty stałe zależne od przyłącza",
    )
    billing_cycle: BillingCycleEnum = BillingCycleEnum.TWO_MONTHS
    billing_period_start_date: date = Field(
        description="Pierwszy dzień okresu rozliczeniowego dla tego obliczenia"
    )


# ==========================================
# 2. KONFIGURACJA FOTOWOLTAIKI (DISCRIMINATED UNION)
# ==========================================

class NoPV(BaseModel):
    mode: Literal["none"] = "none"


class NetBillingPV(BaseModel):
    mode: Literal["net_billing"] = "net_billing"
    type_of_price: TypeOfMarketEnergyEnum = TypeOfMarketEnergyEnum.RCEm


class NetMeteringPV(BaseModel):
    mode: Literal["net_metering"] = "net_metering"
    power_of_pv_kwp: float = Field(gt=0, le=50, description="Moc instalacji (do 50 kWp)")

    @computed_field
    @property
    def effective_k_factor(self) -> float:
        return 0.8 if self.power_of_pv_kwp <= 10.0 else 0.7


PVConfig = Annotated[
    NoPV | NetMeteringPV | NetBillingPV,
    Field(discriminator="mode")
]


# ==========================================
# 3. TARYFA, ZUŻYCIE I OFERTY CENOWE
# ==========================================

class ConsumptionAndTariff(BaseModel):
    tariff_type: TariffTypeEnum


# ==========================================
# 4. MAIN PROFILE MODEL
# ==========================================

class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_info: BaseInfo
    consumption_and_tariff: ConsumptionAndTariff
    pv_config: PVConfig = Field(default_factory=NoPV)

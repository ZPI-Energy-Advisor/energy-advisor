from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.other import (
    TypeOfMarketEnergyEnum,
    BillingCycleEnum,
    DistributionOperatorEnum,
    PhaseTypeEnum,
    PropertyTypeEnum,
    TariffTypeEnum,
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
    # Wycena energii oddanej od 1.02.2025: RCEm (miesięczna) dla prosumentów, którzy pierwszy raz oddali energię
    # przed 1.07.2024, chyba że złożyli oświadczenie o przejściu na RCE; RCE (z każdego okresu) dla pozostałych.
    type_of_price: TypeOfMarketEnergyEnum = TypeOfMarketEnergyEnum.RCE


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
    """Grupa taryfowa (wspólna dla dystrybucji i zwykłej ceny sprzedawcy) i rodzaj umowy na energię.

    Przy umowie z ceną dynamiczną energia ma cenę z kwadransa, a dystrybucja dalej liczy się według grupy.
    """

    tariff_type: TariffTypeEnum
    dynamic_price: bool = False

    @model_validator(mode="before")
    @classmethod
    def legacy_dynamic(cls, data):
        # Profile zapisane przed rozdzieleniem pól miały „dynamic” jako taryfę: to G11 z ceną dynamiczną.
        if isinstance(data, dict) and data.get("tariff_type") == TariffTypeEnum.DYNAMIC.value:
            return {**data, "tariff_type": TariffTypeEnum.G11.value, "dynamic_price": True}
        return data

    @model_validator(mode="after")
    def group_is_not_dynamic(self):
        if self.tariff_type == TariffTypeEnum.DYNAMIC:
            raise ValueError("tariff_type to grupa taryfowa (np. G11); cenę dynamiczną wybiera pole dynamic_price.")
        return self


# ==========================================
# 4. MAIN PROFILE MODEL
# ==========================================

class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_info: BaseInfo
    consumption_and_tariff: ConsumptionAndTariff
    pv_config: PVConfig = Field(default_factory=NoPV)

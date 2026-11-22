from datetime import date
from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field, model_validator

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

class LocationSource(str, Enum):
    POSTAL_CODE = "postal_code"
    TOWN = "town"
    POSTAL_REGION = "postal_region"
    MANUAL = "manual"


class HomeLocation(BaseModel):
    latitude: float = Field(ge=49.0, le=55.0, strict=True)
    longitude: float = Field(ge=14.0, le=24.5, strict=True)
    source: LocationSource
    label: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=120)

    @computed_field
    @property
    def approximate(self) -> bool:
        return self.source == LocationSource.POSTAL_REGION


class BaseInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type_of_property: PropertyTypeEnum
    year_of_construction: int = Field(gt=1800, le=2027)
    heating_area_m2: float = Field(gt=0, le=10000)
    number_of_residents: int = Field(gt=0)
    town: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
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
    location: HomeLocation | None = Field(
        default=None,
        description="Wyznaczana przy zapisie z miejscowości i kodu; klient przysyła ją tylko z source=manual",
    )

    def address_key(self) -> str:
        return f"{self.postal_code} {self.town}"


# ==========================================
# 2. KONFIGURACJA FOTOWOLTAIKI (DISCRIMINATED UNION)
# ==========================================

MAX_PV_POWER_KWP = 50.0
MAX_PV_ARRAYS = 4


class PVArray(BaseModel):
    power_kwp: float | None = Field(default=None, gt=0, le=MAX_PV_POWER_KWP, strict=True)
    azimuth: int = Field(default=0, ge=-180, le=180, strict=True, description="0 = południe, -90 = wschód, 90 = zachód")
    tilt: int = Field(default=35, ge=0, le=90, strict=True, description="0 = poziomo, 90 = pionowo (elewacja)")
    panel_count: int | None = Field(default=None, gt=0, le=200, strict=True)


class PVInstallation(BaseModel):
    arrays: list[PVArray] = Field(min_length=1, max_length=MAX_PV_ARRAYS)
    panel_power_w: int | None = Field(default=None, ge=50, le=1000, strict=True)
    inverter_power_kw: float | None = Field(default=None, gt=0, le=MAX_PV_POWER_KWP, strict=True)
    estimated: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def power_from_panels(self):
        if self.panel_power_w is not None:
            if any(array.panel_count is None for array in self.arrays):
                raise ValueError("Podaj liczbę paneli w każdej grupie.")
            for array in self.arrays:
                array.power_kwp = round(array.panel_count * self.panel_power_w / 1000, 3)
        elif any(array.power_kwp is None for array in self.arrays):
            raise ValueError("Podaj moc każdej grupy paneli w kWp albo liczbę paneli i moc jednego panelu.")
        if self.total_kwp > MAX_PV_POWER_KWP:
            raise ValueError(f"Łączna moc paneli to najwyżej {MAX_PV_POWER_KWP:g} kWp (mikroinstalacja).")
        return self

    @computed_field
    @property
    def total_kwp(self) -> float:
        return round(sum(array.power_kwp for array in self.arrays), 3)


TYPICAL_PV_INSTALLATION = PVInstallation(
    arrays=[PVArray(power_kwp=6.0, azimuth=0, tilt=35)],
    estimated=True,
)


class NoPV(BaseModel):
    mode: Literal["none"] = "none"


class NetBillingPV(BaseModel):
    mode: Literal["net_billing"] = "net_billing"
    # Wycena energii oddanej od 1.02.2025: RCEm (miesięczna) dla prosumentów, którzy pierwszy raz oddali energię
    # przed 1.07.2024, chyba że złożyli oświadczenie o przejściu na RCE; RCE (z każdego okresu) dla pozostałych.
    type_of_price: TypeOfMarketEnergyEnum = TypeOfMarketEnergyEnum.RCE
    installation: PVInstallation | None = None


class NetMeteringPV(BaseModel):
    mode: Literal["net_metering"] = "net_metering"
    installation: PVInstallation

    @model_validator(mode="before")
    @classmethod
    def legacy_power(cls, data):
        if isinstance(data, dict) and data.get("installation") is None and data.get("power_of_pv_kwp") is not None:
            return {**data, "installation": {"arrays": [{"power_kwp": data["power_of_pv_kwp"]}]}}
        return data

    @computed_field(description="Moc instalacji (do 50 kWp); opust zależy od niej")
    @property
    def power_of_pv_kwp(self) -> float:
        return self.installation.total_kwp

    @computed_field
    @property
    def effective_k_factor(self) -> float:
        return 0.8 if self.power_of_pv_kwp <= 10.0 else 0.7


PVConfig = Annotated[
    NoPV | NetMeteringPV | NetBillingPV,
    Field(discriminator="mode")
]


def pv_installation(pv_config: NoPV | NetMeteringPV | NetBillingPV) -> PVInstallation | None:
    if pv_config.mode == "none":
        return None
    return pv_config.installation or TYPICAL_PV_INSTALLATION.model_copy(deep=True)


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

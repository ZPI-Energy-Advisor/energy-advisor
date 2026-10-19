from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


# ==========================================
# TYPY PODSTAWOWE I ENUMY
# ==========================================

PricePerKwh = Annotated[float, Field(ge=0, le=10.0, description="Cena w zł/kWh")]
EnergyKwh = Annotated[float, Field(ge=0, description="Ilość energii w kWh")]


class PhaseTypeEnum(str, Enum):
    SINGLE_PHASE = "1_phase"
    THREE_PHASE = "3_phase"


class BillingCycleEnum(int, Enum):
    ONE_MONTH = 1
    TWO_MONTHS = 2
    SIX_MONTHS = 6
    TWELVE_MONTHS = 12


class TariffTypeEnum(str, Enum):
    G11 = "G11"
    G12 = "G12"
    G12W = "G12w"
    G13 = "G13"
    G13S = "G13s"
    G14D = "G14d"

    @property
    def required_zones(self) -> int:
        mapping = {"G11": 1, "G12": 2, "G12w": 2, "G13": 3, "G13s": 3, "G14d": 4}
        return mapping[self.value]


# ==========================================
# 1. INPUT OD UŻYTKOWNIKA (Formularz)
# ==========================================

class TechnicalConnectionInfo(BaseModel):
    """Fizyczne parametry instalacji niezbędne do opłat OSD."""
    postal_code: str = Field(pattern=r"^\d{2}-\d{3}$", description="Format XX-XXX")
    phase_type: PhaseTypeEnum = PhaseTypeEnum.THREE_PHASE
    billing_cycle: BillingCycleEnum = BillingCycleEnum.TWO_MONTHS


class AnnualConsumption(BaseModel):
    """Roczne zużycie podawane przez użytkownika."""
    tariff_type: TariffTypeEnum
    annual_imported_kwh_per_zone: list[EnergyKwh] = Field(min_length=1, max_length=4, description="Roczne pobranie energii z sieci w strefach taryfowych")

    @computed_field
    @property
    def total_annual_kwh(self) -> float:
        return sum(self.annual_imported_kwh_per_zone)

    @model_validator(mode="after")
    def validate_zones_count(self) -> "AnnualConsumption":
        expected = self.tariff_type.required_zones
        if len(self.annual_imported_kwh_per_zone) != expected:
            raise ValueError(
                f"Taryfa {self.tariff_type.value} wymaga {expected} stref zużycia, "
                f"podano: {len(self.annual_imported_kwh_per_zone)}."
            )
        return self


# ==========================================
# 2. PV (Twoja logika – oczyszczona z ręcznych stawek)
# ==========================================

class NoPV(BaseModel):
    mode: Literal["none"] = "none"


class NetBillingPV(BaseModel):
    mode: Literal["net_billing"] = "net_billing"
    annual_exported_energy_kwh: EnergyKwh
    self_consumed_energy_kwh: EnergyKwh = 0.0
    custom_buyback_price_per_kwh: PricePerKwh | None = None


class NetMeteringPV(BaseModel):
    mode: Literal["net_metering"] = "net_metering"
    power_of_pv_kwp: float = Field(gt=0, le=50)
    annual_exported_energy_per_zone_kwh: list[EnergyKwh] = Field(min_length=1, max_length=4)
    custom_k_factor: float | None = Field(default=None, gt=0, le=1.0)

    @computed_field
    @property
    def effective_k_factor(self) -> float:
        if self.custom_k_factor is not None:
            return self.custom_k_factor
        return 0.8 if self.power_of_pv_kwp <= 10.0 else 0.7


PVConfig = Annotated[NoPV | NetMeteringPV | NetBillingPV, Field(discriminator="mode")]


# ==========================================
# 3. OFERTA KOMERCYJNA (jeśli user porównuje z cennikiem)
# ==========================================

class CommercialOfferInput(BaseModel):
    """Dane z ulotki lub umowy wolnorynkowej wpisywane przez usera."""
    price_per_zone_kwh: list[PricePerKwh] = Field(min_length=1, max_length=4)
    monthly_commercial_fee_pln: float = Field(default=0.0, ge=0)
    contract_duration_months: int = Field(default=24, ge=1, le=36)
    early_exit_penalty_pln: float = Field(default=0.0, ge=0)


# ==========================================
# 4. GŁÓWNY PAYLOAD WEJŚCIOWY APLIKACJI
# ==========================================

class UserProfile(BaseModel):
    """Kompletny zestaw danych przesyłany z frontendu użytkownika."""
    model_config = ConfigDict(from_attributes=True)

    connection: TechnicalConnectionInfo
    consumption: AnnualConsumption
    pv_config: PVConfig = Field(default_factory=NoPV)
    commercial_offer: CommercialOfferInput | None = None

    @model_validator(mode="after")
    def validate_cross_data(self) -> "UserProfile":
        expected_zones = self.consumption.tariff_type.required_zones

        if isinstance(self.pv_config, NetMeteringPV):
            if len(self.pv_config.annual_exported_energy_per_zone_kwh) != expected_zones:
                raise ValueError(
                    f"W net-meteringu wymagane jest {expected_zones} stref eksportu."
                )

        if self.commercial_offer is not None:
            if len(self.commercial_offer.price_per_zone_kwh) != expected_zones:
                raise ValueError(
                    f"Oferta komercyjna musi zawierać {expected_zones} cen strefowych."
                )

        return self
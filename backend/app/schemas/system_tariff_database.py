from datetime import date
from enum import Enum
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.user_profile import BillingCycleEnum, PricePerKwh



FeePerMonth = Annotated[float, Field(ge=0, le=1000.0, description="Stawka stała w zł/miesiąc")]


class OsdOperatorEnum(str, Enum):
    TAURON = "Tauron Dystrybucja"
    PGE = "PGE Dystrybucja"
    ENEA = "Enea Operator"
    ENERGA = "Energa-Operator"
    STOEN = "Stoen Operator"


# ==========================================
# 1. OGÓLNOKRAJOWE STAWKI I PROGI URZĘDOWE (URE / PSE)
# ==========================================

class CapacityFeeThreshold(BaseModel):
    """
    Pojedynczy przedział opłaty mocowej dla gospodarstw domowych.
    Ustawa o rynku mocy definiuje 4 ryczałtowe progi rocznego zużycia.
    """
    min_kwh_annual: float = Field(ge=0)
    max_kwh_annual: float | None = Field(default=None, description="None oznacza brak górnego limitu (próg otwarty)")
    monthly_fee_net_pln: FeePerMonth

    def matches(self, annual_kwh: float) -> bool:
        if annual_kwh < self.min_kwh_annual:
            return False
        if self.max_kwh_annual is not None and annual_kwh >= self.max_kwh_annual:
            return False
        return True


class TransitionFeeThreshold(BaseModel):
    """Progi opłaty przejściowej (<500 kWh, 500-1200 kWh, >1200 kWh/rok)."""
    min_kwh_annual: float = Field(ge=0)
    max_kwh_annual: float | None = None
    monthly_fee_net_pln: FeePerMonth

    def matches(self, annual_kwh: float) -> bool:
        if annual_kwh < self.min_kwh_annual:
            return False
        if self.max_kwh_annual is not None and annual_kwh >= self.max_kwh_annual:
            return False
        return True


class NationwideRegulatoryFees(BaseModel):
    """
    Opłaty jednakowe w całym kraju, ustalane odgórnie (często raz w roku).
    """
    model_config = ConfigDict(from_attributes=True)

    valid_from: date
    valid_to: date

    # Stawki zmienne ogólnokrajowe (zł/kWh netto)
    quality_fee_per_kwh: PricePerKwh
    renewable_energy_fee_per_kwh: PricePerKwh  # Opłata OZE (często 0.00 zł)
    cogeneration_fee_per_kwh: PricePerKwh

    # Tabele progowe ryczałtów miesięcznych
    capacity_fee_thresholds: list[CapacityFeeThreshold]
    transition_fee_thresholds: list[TransitionFeeThreshold]

    vat_rate: float = Field(default=0.23, description="Podatek VAT (standardowo 23%)")

    def get_capacity_fee(self, annual_kwh: float) -> float:
        for threshold in self.capacity_fee_thresholds:
            if threshold.matches(annual_kwh):
                return threshold.monthly_fee_net_pln
        raise ValueError(f"Brak dopasowania progu opłaty mocowej dla {annual_kwh} kWh.")

    def get_transition_fee(self, annual_kwh: float) -> float:
        for threshold in self.transition_fee_thresholds:
            if threshold.matches(annual_kwh):
                return threshold.monthly_fee_net_pln
        raise ValueError(f"Brak dopasowania progu opłaty przejściowej dla {annual_kwh} kWh.")


# ==========================================
# 2. STAWKI DYSTRYBUCYJNE (OSD) DLA DANEJ TARYFY
# ==========================================

class OsdTariffRates(BaseModel):
    """
    Parametry taryfy dystrybucyjnej zatwierdzone przez URE dla konkretnego OSD i taryfy.
    """
    # 1. Składnik zmienny stawki sieciowej w podziale na strefy (zł/kWh netto)
    variable_network_fee_per_zone: list[PricePerKwh] = Field(min_length=1, max_length=4)

    # 2. Składnik stały stawki sieciowej (zł/miesiąc netto)
    fixed_network_fee_1phase_monthly: FeePerMonth
    fixed_network_fee_3phase_monthly: FeePerMonth

    # 3. Opłata abonamentowa w zależności od cyklu odczytów (zł/miesiąc netto)
    subscription_fee_by_cycle: dict[int, FeePerMonth] = Field(
        description="Klucz: długość cyklu w miesiącach (1, 2, 6, 12)"
    )


# ==========================================
# 3. STAWKI SPRZEDAŻY ENERGII (URE Z URZĘDU)
# ==========================================

class DefaultSupplierRates(BaseModel):
    """
    Stawki energii czynnej zatwierdzone przez URE dla sprzedawcy z urzędu.
    """
    supplier_name: str  # np. "Tauron Sprzedaż Sp. z o.o."
    energy_price_per_zone_net: list[PricePerKwh] = Field(min_length=1, max_length=4)
    commercial_fee_monthly_net: FeePerMonth = Field(
        default=0.0,
        description="W taryfie zatwierdzanej przez URE wynosi zawsze 0.0 zł"
    )


# ==========================================
# 4. GŁÓWNY MODEL SYSTEMOWY (KOMPLET DANYCH DLA DANEJ TARYFY I REGIONU)
# ==========================================

class SystemTariffDatabase(BaseModel):
    """
    Agregat danych zaciąganych do pamięci kalkulatora dla danego OSD,
    sprzedawcy z urzędu i grupy taryfowej.
    """
    model_config = ConfigDict(from_attributes=True)

    osd_operator: OsdOperatorEnum
    tariff_code: str = Field(description="np. G11, G12, G12w, G14d")
    number_of_zones: int = Field(ge=1, le=4)

    # Moduły danych
    regulatory: NationwideRegulatoryFees
    distribution: OsdTariffRates
    supplier_ure: DefaultSupplierRates

    @model_validator(mode="after")
    def validate_zones_consistency(self) -> "SystemTariffDatabase":
        zones = self.number_of_zones
        if len(self.distribution.variable_network_fee_per_zone) != zones:
            raise ValueError(
                f"Taryfa {self.tariff_code} ma {zones} stref, ale zmienna sieciowa OSD "
                f"zawiera {len(self.distribution.variable_network_fee_per_zone)} pozycji."
            )
        if len(self.supplier_ure.energy_price_per_zone_net) != zones:
            raise ValueError(
                f"Taryfa {self.tariff_code} ma {zones} stref, ale cena URE "
                f"zawiera {len(self.supplier_ure.energy_price_per_zone_net)} pozycji."
            )
        return self
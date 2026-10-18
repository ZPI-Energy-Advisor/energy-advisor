from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


# Pojedyncza stawka cenowa za 1 kWh (w zł brutto)
PricePerKwh = Annotated[float, Field(gt=0, le=10.0, description="Cena w zł/kWh")]

# Wolumen energii w pojedynczej strefie (w kWh)
EnergyKwh = Annotated[float, Field(ge=0, description="Ilość energii w kWh")]


# ==========================================
# SŁOWNIKI (ENUMS)
# ==========================================

class PropertyTypeEnum(str, Enum):
    APARTMENT = "apartment"
    SINGLE_FAMILY_HOUSE = "single_family_house"
    TERRACE_HOUSE = "terrace_house"
    RECREATIONAL_COTTAGE = "recreational_cottage"
    OTHER = "other"


class TariffTypeEnum(str, Enum):
    G11 = "G11"    # 1 strefa
    G12 = "G12"    # 2 strefy
    G12W = "G12w"  # 2 strefy
    G13 = "G13"    # 3 strefy
    G13S = "G13s"  # 3 strefy
    G14D = "G14d"  # 4 strefy

    @property
    def required_zones(self) -> int:
        """Zwraca wymaganą liczbę stref dla danej taryfy."""
        mapping = {
            "G11": 1,
            "G12": 2,
            "G12w": 2,
            "G13": 3,
            "G13s": 3,
            "G14d": 4,
        }
        return mapping[self.value]


# ==========================================
# 1. INFORMACJE PODSTAWOWE O BUDYNKU
# ==========================================

class BaseInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type_of_property: PropertyTypeEnum
    year_of_construction: int = Field(gt=1800, le=2027)
    heating_area_m2: float = Field(gt=0, le=10000)
    number_of_residents: int = Field(gt=0)
    town: str = Field(min_length=1, max_length=100)


# ==========================================
# 2. KONFIGURACJA FOTOWOLTAIKI (DISCRIMINATED UNION)
# ==========================================

class NoPV(BaseModel):
    mode: Literal["none"] = "none"


class NetBillingPV(BaseModel):
    """Nowy system (wartościowy): energia oddana wpada do jednego worka finansowego."""
    mode: Literal["net_billing"] = "net_billing"
    exported_energy_total_kwh: float = Field(gt=0, description="Suma energii oddanej do sieci w roku (kWh)")
    self_consumed_energy_kwh: float = Field(default=0.0, ge=0, description="Autokonsumpcja (statystycznie)")
    type_of_price: Literal["RCE", "RCEm"] = "RCEm"
    estimated_buyback_price_per_kwh: PricePerKwh = Field(description="Szacowana cena odkupu (RCE/RCEm) w zł/kWh")


class NetMeteringPV(BaseModel):
    """Stary system (opusty): energia oddana musi być rozbita na strefy taryfy."""
    mode: Literal["net_metering"] = "net_metering"
    power_of_pv_kwp: float = Field(gt=0, le=50, description="Moc instalacji (do 50 kWp)")
    exported_energy_per_zone_kwh: list[EnergyKwh] = Field(min_length=1, max_length=4)
    custom_k_factor: float | None = Field(
        default=None, gt=0, le=1.0,
        description="Opcjonalny mnożnik (np. 1.0 dla ofert z wirtualnym magazynem 1:1)"
    )

    @computed_field
    @property
    def effective_k_factor(self) -> float:
        """Zwraca nadpisany mnożnik lub ustawowe 0.8 (<=10 kWp) / 0.7 (>10 kWp)."""
        if self.custom_k_factor is not None:
            return self.custom_k_factor
        return 0.8 if self.power_of_pv_kwp <= 10.0 else 0.7


PVConfig = Annotated[
    NoPV | NetMeteringPV | NetBillingPV,
    Field(discriminator="mode")
]


# ==========================================
# 3. TARYFA, ZUŻYCIE I OFERTY CENOWE
# ==========================================

class ConsumptionAndTariff(BaseModel):
    """Aktualna taryfa użytkownika, zużycie w strefach oraz ceny URE."""
    tariff_type: TariffTypeEnum
    imported_energy_per_zone_kwh: list[EnergyKwh] = Field(
        min_length=1, max_length=4,
        description="Energia pobrana z sieci w podziale na strefy"
    )
    ure_price_per_zone_kwh: list[PricePerKwh] = Field(
        min_length=1, max_length=4,
        description="Stawki taryfowe URE za 1 kWh w poszczególnych strefach"
    )

    @model_validator(mode="after")
    def validate_zones_count(self) -> "ConsumptionAndTariff":
        expected = self.tariff_type.required_zones
        if len(self.imported_energy_per_zone_kwh) != expected:
            raise ValueError(
                f"Taryfa {self.tariff_type.value} wymaga dokładnie {expected} stref zużycia "
                f"(podano {len(self.imported_energy_per_zone_kwh)})."
            )
        if len(self.ure_price_per_zone_kwh) != expected:
            raise ValueError(
                f"Taryfa {self.tariff_type.value} wymaga dokładnie {expected} stawek cenowych URE "
                f"(podano {len(self.ure_price_per_zone_kwh)})."
            )
        return self


class CommercialOffer(BaseModel):
    """Parametry oferty wolnorynkowej do porównania z taryfą URE."""
    price_per_zone_kwh: list[PricePerKwh] = Field(min_length=1, max_length=4)
    monthly_commercial_fee_pln: float = Field(default=0.0, ge=0, description="Opłata handlowa sprzedawcy (zł/m-c)")
    early_exit_penalty_pln: float = Field(default=0.0, ge=0, description="Kara umowna za zerwanie umowy (zł)")


class DistributionFees(BaseModel):
    """Opcjonalne koszty OSD (identyczne dla obu ofert, potrzebne do pełnego rachunku)."""
    fixed_monthly_osd_fee_pln: float = Field(
        default=0.0, ge=0,
        description="Suma stałych opłat OSD: sieciowa stała, mocowa, abonamentowa, przejściowa (zł/m-c)"
    )
    variable_osd_fee_per_zone_kwh: list[Annotated[float, Field(ge=0, le=5.0)]] | None = Field(
        default=None,
        description="Zmienne stawki dystrybucyjne za 1 kWh w strefach"
    )


# ==========================================
# 4. GŁÓWNY PROFIL / PAYLOAD KALKULATORA
# ==========================================

class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_info: BaseInfo
    consumption_and_tariff: ConsumptionAndTariff
    pv_config: PVConfig = Field(default_factory=NoPV)
    commercial_offer: CommercialOffer | None = None
    distribution_fees: DistributionFees = Field(default_factory=DistributionFees)

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "UserProfile":
        expected_zones = self.consumption_and_tariff.tariff_type.required_zones

        # 1. Sprawdzenie liczby stref w Net-Meteringu
        if isinstance(self.pv_config, NetMeteringPV):
            if len(self.pv_config.exported_energy_per_zone_kwh) != expected_zones:
                raise ValueError(
                    f"W net-meteringu dla taryfy {self.consumption_and_tariff.tariff_type.value} "
                    f"musisz podać eksport energii dla {expected_zones} stref."
                )

        # 2. Sprawdzenie liczby stref w ofercie komercyjnej
        if self.commercial_offer is not None:
            if len(self.commercial_offer.price_per_zone_kwh) != expected_zones:
                raise ValueError(
                    f"Oferta komercyjna musi mieć {expected_zones} stawek cenowych "
                    f"(zgodnie z taryfą {self.consumption_and_tariff.tariff_type.value})."
                )

        # 3. Sprawdzenie liczby stref w opłatach zmiennych OSD (jeśli podano)
        if self.distribution_fees.variable_osd_fee_per_zone_kwh is not None:
            if len(self.distribution_fees.variable_osd_fee_per_zone_kwh) != expected_zones:
                raise ValueError(
                    f"Opłaty zmienne OSD muszą mieć {expected_zones} stref "
                    f"(zgodnie z taryfą {self.consumption_and_tariff.tariff_type.value})."
                )

        return self
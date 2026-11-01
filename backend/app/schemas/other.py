from enum import Enum
from typing import Annotated
from datetime import datetime
from typing import TypeAlias
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator



PricePerKwh = Annotated[float, Field(ge=0, le=10.0, description="Cena w zł/kWh")]
EnergyKwh = Annotated[float, Field(ge=0, description="Ilość energii w kWh")]
EnergyKwhList = Annotated[list[EnergyKwh], Field(min_length=1, max_length=4, description="Lista zużycia energii w kWh w strefach taryfowych (1-4 strefy)")]


EnergyRecord: TypeAlias = tuple[datetime, float]

EnergyCycle: TypeAlias = tuple[datetime, list[EnergyRecord]]

EnergyTimeSeries: TypeAlias = list[EnergyCycle]

BalancedMeteringCycle: TypeAlias = tuple[datetime, list[float]]

BalancedBillingCycle: TypeAlias = dict[datetime, float]


class PropertyTypeEnum(str, Enum):
    APARTMENT = "apartment"
    SINGLE_FAMILY_HOUSE = "single_family_house"
    TERRACE_HOUSE = "terrace_house"
    RECREATIONAL_COTTAGE = "recreational_cottage"
    OTHER = "other"

class PhaseTypeEnum(str, Enum):
    SINGLE_PHASE = "1_phase"
    THREE_PHASE = "3_phase"


class DistributionOperatorEnum(str, Enum):
    PGE = "PGE"
    TAURON = "TAURON"
    ENEA = "ENEA"
    ENERGA = "ENERGA"
    STOEN = "STOEN"

    @classmethod
    def _missing_(cls, value):
        legacy_values = {
            "PGE Dystrybucja": cls.PGE,
            "TAURON Dystrybucja": cls.TAURON,
            "Enea Operator": cls.ENEA,
            "Energa-Operator": cls.ENERGA,
            "Stoen Operator": cls.STOEN,
        }
        return legacy_values.get(value)


class BillingCycleEnum(int, Enum):
    ONE_MONTH = 1
    TWO_MONTHS = 2
    SIX_MONTHS = 6
    TWELVE_MONTHS = 12


class TypeOfMarketEnergyEnum(str, Enum):
    RCE = "RCE"
    RCEm = "RCEm"

class PVTypeEnum(str, Enum):
    NET_METERING = "net_metering"
    NET_BILLING = "net_billing"

class TariffTypeEnum(str, Enum):
    G11 = "G11"
    G12 = "G12"
    G12W = "G12w"
    G13 = "G13"
    G13S = "G13s"
    G14D = "G14d"
    DYNAMIC = "dynamic"

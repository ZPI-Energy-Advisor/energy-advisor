from datetime import date, datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DeviceUsageGroupBy(str, Enum):
    CATEGORY = "category"
    TYPE = "type"
    INSTANCE = "instance"


class DeviceUsageResolution(str, Enum):
    QUARTER = "15m"
    HOUR = "1h"
    DAY = "1d"


class DeviceUsageTariff(BaseModel):
    name: str
    source: Literal["query", "profile", "default"]
    note: str | None = None


class KwhSeries(BaseModel):
    """Wartości w kolejnych okresach z `periods` odpowiedzi i ich suma."""

    kwh: list[float]
    total_kwh: float


class EnergySeries(KwhSeries):
    cost_pln: list[float]
    total_cost_pln: float


class DeviceUsageGroup(EnergySeries):
    key: str
    label: str
    category: str | None = None
    device_type: str | None = None
    device_type_label: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    devices_count: int
    # Ile urządzeń grupy można przenieść na inne godziny (tryb shiftable albo interruptible).
    flexible_devices_count: int = 0
    # Tylko group_by=instance: fixed, shiftable albo interruptible.
    flexibility_mode: str | None = None


class RestOfHouse(EnergySeries):
    """Zużycie licznika, którego nie opisują urządzenia: licznik − urządzenia, w dniach wspólnych obu źródeł."""

    meter_file_ids: list[UUID]
    common_days: list[date]
    exceeded_days: list[date]


class DeviceUsageResponse(BaseModel):
    source_id: str
    date_from: date
    date_to: date
    group_by: DeviceUsageGroupBy
    resolution: DeviceUsageResolution
    tariff: DeviceUsageTariff
    periods: list[datetime]
    groups: list[DeviceUsageGroup]
    production: KwhSeries | None = None
    rest_of_house: RestOfHouse | None = None
    total_kwh: float
    total_cost_pln: float
    missing_price_slots: int = 0

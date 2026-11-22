from datetime import date
from typing import Any

from pydantic import BaseModel

from app.schemas.calculation import AnnualConsumption, UnsupportedTariffInfo


class TariffComparisonItem(BaseModel):
    key: str
    label: str
    name: str | None = None
    type: str
    tariff_code: str
    distribution_group: str
    is_profile: bool
    note: str | None = None
    billing_cycle_months: int | None = None
    payable_gross: float | None = None
    gross_total: float | None = None
    active_energy_gross: float | None = None
    deposit_amount: float | None = None
    deposit_applied: float | None = None
    energy_cost_pln: float | None = None
    monthly_fees_pln: float | None = None
    monthly_fee_gross: float | None = None
    cost_breakdown: dict[str, float] | None = None
    cycles: list[dict[str, Any]] = []
    difference_to_profile: float | None = None


class TariffRecommendation(BaseModel):
    tariff: str
    is_current: bool
    saving: float | None = None
    saving_percent: float | None = None
    monthly_saving_estimate: float | None = None
    difference_to_cheapest: float | None = None
    skipped_tariffs: list[str] = []


class TariffComparisonResponse(BaseModel):
    source_id: str
    source_name: str
    source_type: str
    date_from: date
    date_to: date
    billed_from: date
    billed_to: date
    all_tariffs: bool
    operator: str
    from_profile: bool
    profile_tariff: str
    selected_tariff: str
    selection_note: str | None = None
    billing_cycle_months: int
    pv_mode: str | None = None
    annual_consumption: AnnualConsumption
    cheapest_tariff: str | None = None
    recommendation: TariffRecommendation | None = None
    tariffs: list[TariffComparisonItem]
    warnings: list[str] = []
    unsupported_tariffs: list[UnsupportedTariffInfo] = []

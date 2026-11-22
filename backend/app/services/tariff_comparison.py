from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple

from app.schemas.other import TariffTypeEnum
from app.services.new_calculations_service import TariffKey, TariffRun, key_order, result_for
from app.services.quarter_prices import FeeParameters, monthly_fees
from app.services.tariff_costs import DYNAMIC_TYPE, ZONED_TYPE, tariff_key, tariff_label
from app.services.tariff_engine import money
from app.services.tariff_zones import covers

ZERO = Decimal("0")
# Różnica mniejsza niż złotówka to remis: zostawiamy taryfę, którą użytkownik już ma.
TIE_THRESHOLD_PLN = 1.0
# Szacunek miesięczny tylko z okresu co najmniej miesięcznego; z kilku dni byłby zgadywaniem.
MIN_DAYS_FOR_MONTHLY_ESTIMATE = 28
AVERAGE_MONTH_DAYS = 365.25 / 12
ENERGY_PARTS = {
    "energy": ("active_energy_net",),
    "distribution": ("variable_network_net",),
    "fees": ("excise_net", "quality_net", "renewable_net", "cogeneration_net"),
}


class Reading(NamedTuple):
    measured_at: datetime
    energy_kwh: float
    exported_kwh: float


def readings_from_usage(
    usage: dict[str, list[float | None]], exports: dict[tuple[str, int], float] | None = None
) -> list[Reading]:
    exports = exports or {}
    return [
        Reading(datetime.fromisoformat(day) + timedelta(minutes=15 * slot), float(kwh), exports.get((day, slot), 0.0))
        for day, slots in sorted(usage.items())
        for slot, kwh in enumerate(slots)
        if kwh is not None
    ]


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def bill_parts(result: dict) -> dict[str, Any]:
    sums = dict.fromkeys(ENERGY_PARTS, ZERO)
    energy_gross = ZERO
    for cycle in result["cycles"]:
        net_total = _decimal(cycle["net_total"])
        ratio = _decimal(cycle["gross_total"]) / net_total if net_total else Decimal(1)
        cycle_energy = ZERO
        for part, names in ENERGY_PARTS.items():
            value = sum((_decimal(cycle[name]) for name in names), ZERO)
            sums[part] += value
            cycle_energy += value
        energy_gross += cycle_energy * ratio
    energy_gross = money(energy_gross)
    payable = _decimal(result["payable_gross"])
    energy_cost = max(energy_gross - _decimal(result["deposit_applied"]), ZERO)
    breakdown = {part: money(value) for part, value in sums.items()}
    breakdown["vat"] = energy_gross - sum(breakdown.values(), ZERO)
    return {
        "energy_cost_pln": float(energy_cost),
        "monthly_fees_pln": float(payable - energy_cost),
        "cost_breakdown": {part: float(value) for part, value in breakdown.items()},
    }


def _monthly_fee_gross(run: TariffRun, definitions: list, months: int) -> float | None:
    day = run.last_day
    definition = next((item for item in reversed(definitions) if covers(item, day)), definitions[-1])
    period = next((item for item in run.regulatory_periods if covers(item, day)), None)
    if period is None:
        return None
    details = run.details
    parameters = FeeParameters(
        details.tariff_data.phase_type, months, _decimal(details.annual_consumption.annual_kwh),
        details.pv_details is not None,
    )
    try:
        return float(money(monthly_fees(definition, period, parameters).gross))
    except ValueError:
        return None


def _name(definitions: list) -> str | None:
    return next((item.name for item in reversed(definitions) if item.name), None)


def _note(run: TariffRun, key: TariffKey) -> str | None:
    code, group = key
    details = run.details
    notes = details.tariff_notes or {}
    errors = details.tariff_calculation_errors or {}
    error_name = f"dynamic {group.value}" if code == TariffTypeEnum.DYNAMIC else code.value
    return errors.get(error_name) or notes.get(code.value)


def tariff_entries(run: TariffRun) -> list[dict[str, Any]]:
    entries = []
    profile_inputs = run.inputs
    for key in sorted(run.definitions, key=key_order):
        code, group = key
        result = result_for(run.details, key)
        note = None if result is not None else _note(run, key)
        if result is None and note is None:
            continue
        definitions = run.definitions[key]
        entry = {
            "key": tariff_key(code, group),
            "label": tariff_label(code, group),
            "name": _name(definitions),
            "type": DYNAMIC_TYPE if code == TariffTypeEnum.DYNAMIC else ZONED_TYPE,
            "tariff_code": code.value,
            "distribution_group": group.value,
            "is_profile": profile_inputs.from_profile and key == run.profile_key,
            "note": note,
        }
        if result is None:
            entries.append({**entry, "payable_gross": None})
            continue
        months = result["billing_cycle_months"]
        entries.append({
            **entry,
            "billing_cycle_months": months,
            "payable_gross": result["payable_gross"],
            "gross_total": result["gross_total"],
            "deposit_amount": result["deposit_amount"],
            "deposit_applied": result["deposit_applied"],
            "monthly_fee_gross": _monthly_fee_gross(run, definitions, months),
            **bill_parts(result),
            "cycles": result["cycles"],
        })
    return entries


def recommendation(entries: list[dict], reference_key: str | None, billed_days: int) -> dict[str, Any] | None:
    priced = [entry for entry in entries if entry["payable_gross"] is not None]
    skipped = [entry["key"] for entry in entries if entry["payable_gross"] is None]
    cheapest = min(priced, key=lambda entry: entry["payable_gross"], default=None)
    if cheapest is None:
        return None
    reference = next((entry for entry in priced if entry["key"] == reference_key), None)
    base = {"skipped_tariffs": skipped, "difference_to_cheapest": None}
    if reference is None:
        return {
            **base, "tariff": cheapest["key"], "is_current": False,
            "saving": None, "saving_percent": None, "monthly_saving_estimate": None,
        }
    difference = round(reference["payable_gross"] - cheapest["payable_gross"], 2)
    if difference < TIE_THRESHOLD_PLN:
        return {
            **base, "tariff": reference["key"], "is_current": True, "difference_to_cheapest": difference,
            "saving": 0.0, "saving_percent": 0.0, "monthly_saving_estimate": None,
        }
    percent = round(difference / reference["payable_gross"] * 100, 1) if reference["payable_gross"] > 0 else None
    monthly = (
        round(difference * AVERAGE_MONTH_DAYS / billed_days, 2) if billed_days >= MIN_DAYS_FOR_MONTHLY_ESTIMATE else None
    )
    return {
        **base, "tariff": cheapest["key"], "is_current": False, "difference_to_cheapest": difference,
        "saving": difference, "saving_percent": percent, "monthly_saving_estimate": monthly,
    }


def comparison(run: TariffRun) -> dict[str, Any]:
    details = run.details
    entries = tariff_entries(run)
    selected = tariff_key(*run.selected_key)
    priced = [entry for entry in entries if entry["payable_gross"] is not None]
    reference = next((entry["payable_gross"] for entry in priced if entry["key"] == selected), None)
    for entry in entries:
        entry["difference_to_profile"] = (
            None if reference is None or entry["payable_gross"] is None
            else round(entry["payable_gross"] - reference, 2)
        )
    cheapest = min(priced, key=lambda entry: entry["payable_gross"], default=None)
    profile_tariff = tariff_key(*run.profile_key)
    return {
        "operator": details.tariff_data.distribution_operator.value,
        "from_profile": run.inputs.from_profile,
        "profile_tariff": profile_tariff,
        "selected_tariff": selected,
        "selection_note": run.selection_note,
        "billing_cycle_months": details.tariff_data.billing_cycle.value,
        "billed_from": run.first_day,
        "billed_to": run.last_day,
        "pv_mode": details.pv_details.mode.value if details.pv_details is not None else None,
        "annual_consumption": details.annual_consumption,
        "cheapest_tariff": cheapest["key"] if cheapest else None,
        "recommendation": recommendation(
            entries, profile_tariff if run.inputs.from_profile else None, (run.last_day - run.first_day).days + 1
        ),
        "tariffs": entries,
        "warnings": details.warnings or [],
        "unsupported_tariffs": details.unsupported_tariffs or [],
    }

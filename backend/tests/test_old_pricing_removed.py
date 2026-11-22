import importlib.util

from sqlalchemy import inspect

from app.database import engine
from conftest import BACKEND_DIR

MIGRATION = BACKEND_DIR / "alembic" / "versions" / "f2c7a9d4e1b8_usuniecie_starego_cennika.py"


def _migration():
    spec = importlib.util.spec_from_file_location("old_pricing_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_old_price_list_tables_are_gone(db):
    tables = set(inspect(engine).get_table_names())

    assert not tables & {"tariffs", "tariff_rates"}
    assert "tariff_definitions" in tables


def test_migration_removes_costs_from_old_price_list_and_keeps_usage():
    results = {
        "usage_15min": {"2026-01-01": [0.25] * 96},
        "slot_prices": {"G11": {"type": "stala", "prices": [1.0] * 96}},
        "tariffs": {"G11": {"type": "stala", "estimated_cost_pln": 24.0}},
        "total_usage_kwh": 24.0,
        "chart_hourly": [{"hour": "00:00", "kwh": 1.0, "cost_G11": 1.0, "price_G11": 1.0}],
        "chart_15min": [{"time": "00:00", "kwh": 0.25, "cost_Dynamiczna": None, "price_Dynamiczna": None}],
        "chart_daily": [{"date": "2026-01-01", "kwh": 24.0, "cost_G11": 24.0}],
        "statistics": {"resolution_minutes": 60},
        "import_report": {"rows_imported": 24},
    }

    cleaned = _migration().without_old_pricing(results)

    assert cleaned == {
        "usage_15min": {"2026-01-01": [0.25] * 96},
        "total_usage_kwh": 24.0,
        "chart_hourly": [{"hour": "00:00", "kwh": 1.0}],
        "chart_15min": [{"time": "00:00", "kwh": 0.25}],
        "chart_daily": [{"date": "2026-01-01", "kwh": 24.0}],
        "statistics": {"resolution_minutes": 60},
        "import_report": {"rows_imported": 24},
    }
    assert "slot_prices" in results


def test_migration_keeps_results_without_old_costs():
    results = {"usage_15min": {}, "total_usage_kwh": 0.0, "chart_daily": [], "statistics": {}}

    assert _migration().without_old_pricing(results) == results

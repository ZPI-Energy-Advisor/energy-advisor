import pytest
from datetime import date, datetime
from io import BytesIO
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.services.calculation_service import CalculationService, public_results

format_hour_label = CalculationService.format_hour_label

def _get_mock_repository():
    mock_repository = MagicMock()
    mock_tariff = MagicMock()
    mock_tariff.id = 1
    mock_tariff.name = "G11"
    mock_tariff.type = "stala"
    
    mock_rate = MagicMock()
    mock_rate.time_start = datetime.strptime("00:00:00", "%H:%M:%S").time()
    mock_rate.time_end = datetime.strptime("23:59:59", "%H:%M:%S").time()
    mock_rate.price_per_kwh = 1.0

    mock_repository.get_all.return_value = [mock_tariff]
    mock_repository.get_rates_for_tariff.return_value = [mock_rate]
    return mock_repository

def test_format_hour_label():
    assert format_hour_label(datetime(2025, 8, 9, 14, 15)) == "14:00"
    assert format_hour_label(datetime(2025, 8, 9, 0, 45)) == "00:00"
    assert format_hour_label(datetime(2025, 8, 9, 1, 0)) == "00:00"
    assert format_hour_label(datetime(2025, 8, 9, 0, 0)) == "23:00"

def test_calculate_old_format_success():
    csv_content = """Data;Wartość kWh;Rodzaj
    2024-11-03 1:00;0,65;pobór
    2024-11-03 2:00;0,50;pobór
    2024-11-03 24:00;1,00;pobór"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    results = CalculationService(_get_mock_repository()).calculate_all_tariffs(dummy_file)

    assert results["statistics"]["data_start"] == "2024-11-03"
    assert results["tariffs"]["G11"]["total_usage_kwh"] == 2.15

def test_calculate_new_format_with_excel_bug_and_oddanie():
    csv_content = """Data i godzina;Wartosc[kWh/kvar];Rodzaj energii
07.06.2026 01:00;1,00;pobór
07.06.2026 02:00;5,00;oddanie
46181;2,00;pobór"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    results = CalculationService(_get_mock_repository()).calculate_all_tariffs(dummy_file)

    assert results["tariffs"]["G11"]["total_usage_kwh"] == 3.00
    
    assert results["statistics"]["days_analyzed"] == 1
    assert results["statistics"]["data_start"] == "2026-06-07"
    
    assert results["statistics"]["has_missing_data"] is True

def test_calculate_only_oddanie_raises_400():
    csv_content = """Data i godzina;Wartosc[kWh/kvar];Rodzaj energii
07.06.2026 01:00;5,00;oddanie
07.06.2026 02:00;5,00;oddanie"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    
    with pytest.raises(HTTPException) as exc_info:
        CalculationService(_get_mock_repository()).calculate_all_tariffs(dummy_file)
    
    assert exc_info.value.status_code == 400
    assert "tylko dane o oddaniu" in str(exc_info.value.detail)


def test_calculate_bad_columns_raises_422():
    csv_content = "Totalna;Bzdura\n1;2"
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    
    with pytest.raises(HTTPException) as exc_info:
        CalculationService(_get_mock_repository()).calculate_all_tariffs(dummy_file)
    
    assert exc_info.value.status_code == 422
    assert "Nierozpoznany format" in str(exc_info.value.detail)

def _hourly_csv(daily_values):
    """CSV z pełnymi dobami (01:00-24:00); każdy dzień ma stałe zużycie godzinowe."""
    lines = ["Data;Wartość kWh;Rodzaj"]
    for day, kwh in daily_values.items():
        for hour in range(1, 25):
            lines.append(f"{day} {hour}:00;{str(kwh).replace('.', ',')};pobór")
    return BytesIO("\n".join(lines).encode("utf-8"))


def _results_for_days():
    csv_file = _hourly_csv({"2024-05-01": 1.0, "2024-05-02": 2.0, "2024-05-03": 3.0})
    return CalculationService(_get_mock_repository()).calculate_all_tariffs(csv_file)


def test_results_contain_usage_series_for_ranges():
    results = _results_for_days()

    assert list(results["usage_15min"]) == ["2024-05-01", "2024-05-02", "2024-05-03"]
    assert all(len(slots) == 96 and None not in slots for slots in results["usage_15min"].values())
    assert results["slot_prices"]["G11"] == {"type": "stala", "prices": [1.0] * 96}
    assert public_results(results).keys() == {"tariffs", "chart_15min", "chart_hourly", "chart_daily", "statistics"}


def test_full_range_matches_import_results():
    results = _results_for_days()

    ranged = CalculationService.calculate_for_range(results, date(2024, 5, 1), date(2024, 5, 3))

    assert ranged == public_results(results)


def test_range_limits_charts_totals_and_statistics():
    results = _results_for_days()

    ranged = CalculationService.calculate_for_range(results, date(2024, 5, 2), date(2024, 5, 3))

    assert [row["date"] for row in ranged["chart_daily"]] == ["2024-05-02", "2024-05-03"]
    assert ranged["tariffs"]["G11"]["total_usage_kwh"] == 120.0
    assert ranged["tariffs"]["G11"]["estimated_cost_pln"] == 120.0
    assert ranged["statistics"]["data_start"] == "2024-05-02"
    assert ranged["statistics"]["data_end"] == "2024-05-03"
    assert ranged["statistics"]["days_analyzed"] == 2
    assert ranged["statistics"]["records_count"] == 48


def test_range_end_date_is_inclusive():
    results = _results_for_days()

    ranged = CalculationService.calculate_for_range(results, date(2024, 5, 2), date(2024, 5, 2))

    assert [row["date"] for row in ranged["chart_daily"]] == ["2024-05-02"]
    assert ranged["tariffs"]["G11"]["total_usage_kwh"] == 48.0


@pytest.mark.parametrize("chart, points", [("chart_hourly", 24), ("chart_15min", 96)])
def test_range_applies_to_every_resolution(chart, points):
    results = _results_for_days()

    first_day = CalculationService.calculate_for_range(results, date(2024, 5, 1), date(2024, 5, 1))
    last_day = CalculationService.calculate_for_range(results, date(2024, 5, 3), date(2024, 5, 3))

    # Profil doby liczony jest tylko z dni w zakresie: 1 kWh/h w pierwszym dniu, 3 kWh/h w ostatnim.
    per_point = 1.0 if chart == "chart_hourly" else 0.25
    assert len(first_day[chart]) == points
    assert {row["kwh"] for row in first_day[chart]} == {per_point}
    assert {row["kwh"] for row in last_day[chart]} == {round(per_point * 3, 2)}


def test_range_without_data_returns_empty_results():
    results = _results_for_days()

    ranged = CalculationService.calculate_for_range(results, date(2024, 6, 1), date(2024, 6, 30))

    assert ranged["chart_daily"] == [] and ranged["chart_hourly"] == [] and ranged["chart_15min"] == []
    assert ranged["tariffs"]["G11"] == {"type": "stala", "total_usage_kwh": 0.0, "estimated_cost_pln": 0.0}
    assert ranged["statistics"]["days_analyzed"] == 0


def _day(kwh, slots=range(96)):
    """Doba z wartością kWh w podanych kwadransach i brakiem pomiaru w pozostałych."""
    selected = set(slots)
    return [kwh if slot in selected else None for slot in range(96)]


def _source(usage):
    return {"usage_15min": usage}


def test_merge_single_file_keeps_its_data():
    usage = {"2024-01-01": _day(0.25), "2024-01-02": _day(0.5)}

    merged, contributions = CalculationService.merge_usage([_source(usage)])

    assert merged == usage
    assert contributions == [{"days_used": 2, "slots_used": 192}]


def test_merge_files_with_gap_keeps_gap_empty():
    january = {"2024-01-30": _day(0.25), "2024-01-31": _day(0.25)}
    march = {"2024-03-01": _day(0.5)}

    merged, contributions = CalculationService.merge_usage([_source(january), _source(march)])

    assert list(merged) == ["2024-01-30", "2024-01-31", "2024-03-01"]
    assert contributions == [{"days_used": 2, "slots_used": 192}, {"days_used": 1, "slots_used": 96}]


def test_merge_overlap_newer_upload_wins():
    older = {"2024-06-01": _day(0.25), "2024-06-02": _day(0.25)}
    newer = {"2024-06-02": _day(0.75), "2024-06-03": _day(0.75)}

    merged, contributions = CalculationService.merge_usage([_source(older), _source(newer)])

    assert merged["2024-06-01"] == _day(0.25)
    assert merged["2024-06-02"] == _day(0.75)
    assert merged["2024-06-03"] == _day(0.75)
    assert contributions == [{"days_used": 1, "slots_used": 96}, {"days_used": 2, "slots_used": 192}]


def test_merge_order_decides_which_overlap_wins():
    first = {"2024-06-01": _day(0.25)}
    second = {"2024-06-01": _day(0.75)}

    merged, _ = CalculationService.merge_usage([_source(second), _source(first)])

    assert merged["2024-06-01"] == _day(0.25)


def test_merge_identical_files_does_not_double_usage():
    usage = {"2024-06-01": _day(0.25), "2024-06-02": _day(0.25)}

    merged, contributions = CalculationService.merge_usage([_source(usage), _source(dict(usage))])

    assert merged == usage
    total = sum(kwh for day in merged.values() for kwh in day)
    assert total == pytest.approx(48.0)
    # Starszy plik nie dostarcza już niczego - wszystkie kwadranse przejął nowszy.
    assert contributions == [{"days_used": 0, "slots_used": 0}, {"days_used": 2, "slots_used": 192}]


def test_merge_partial_day_is_completed_by_older_file():
    older = {"2024-06-01": _day(0.25)}
    newer = {"2024-06-01": _day(0.75, slots=range(48))}

    merged, contributions = CalculationService.merge_usage([_source(older), _source(newer)])

    assert merged["2024-06-01"][:48] == [0.75] * 48
    assert merged["2024-06-01"][48:] == [0.25] * 48
    assert contributions == [{"days_used": 1, "slots_used": 48}, {"days_used": 1, "slots_used": 48}]


def test_merge_newer_file_inside_older_range():
    older = {f"2024-06-{day:02d}": _day(0.25) for day in range(1, 31)}
    newer = {"2024-06-10": _day(1.0), "2024-06-11": _day(1.0)}

    merged, contributions = CalculationService.merge_usage([_source(older), _source(newer)])

    assert len(merged) == 30
    assert merged["2024-06-09"] == _day(0.25) and merged["2024-06-10"] == _day(1.0)
    assert contributions == [{"days_used": 28, "slots_used": 28 * 96}, {"days_used": 2, "slots_used": 192}]


def test_merge_missing_slots_in_both_files_stay_missing():
    older = {"2024-06-01": _day(0.25, slots=range(0, 10))}
    newer = {"2024-06-01": _day(0.75, slots=range(5, 20))}

    merged, _ = CalculationService.merge_usage([_source(older), _source(newer)])

    assert merged["2024-06-01"][:5] == [0.25] * 5
    assert merged["2024-06-01"][5:20] == [0.75] * 15
    assert merged["2024-06-01"][20:] == [None] * 76

import math

import pytest
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from fastapi import HTTPException

from app.services.calculation_service import (
    ACTIONS_PER_DAY_KEY,
    CalculationService,
    public_results,
    source_resolution,
)

format_hour_label = CalculationService.format_hour_label


def _for_range(results, date_from, date_to):
    """Wykresy i statystyki dni [date_from, date_to] tak jak w `/data`."""
    return CalculationService.summarize_usage(
        CalculationService.usage_in_range(results["usage_15min"], date_from, date_to),
        {},
        source_resolution(results),
        results.get(ACTIONS_PER_DAY_KEY),
    )


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
    results = CalculationService().summarize_file(dummy_file)

    assert results["statistics"]["data_start"] == "2024-11-03"
    assert results["total_usage_kwh"] == 2.15

def test_calculate_new_format_with_excel_bug_and_oddanie():
    csv_content = """Data i godzina;Wartosc[kWh/kvar];Rodzaj energii
07.06.2026 01:00;1,00;pobór
07.06.2026 02:00;5,00;oddanie
46181;2,00;pobór"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    results = CalculationService().summarize_file(dummy_file)

    assert results["total_usage_kwh"] == 3.00
    
    assert results["statistics"]["days_analyzed"] == 1
    assert results["statistics"]["data_start"] == "2026-06-07"
    
    assert results["statistics"]["has_missing_data"] is True

def test_calculate_only_oddanie_raises_400():
    csv_content = """Data i godzina;Wartosc[kWh/kvar];Rodzaj energii
07.06.2026 01:00;5,00;oddanie
07.06.2026 02:00;5,00;oddanie"""
    
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    
    with pytest.raises(HTTPException) as exc_info:
        CalculationService().summarize_file(dummy_file)
    
    assert exc_info.value.status_code == 400
    assert "tylko dane o oddaniu" in str(exc_info.value.detail)


def test_calculate_bad_columns_raises_422():
    csv_content = "Totalna;Bzdura\n1;2"
    dummy_file = BytesIO(csv_content.encode('utf-8'))
    
    with pytest.raises(HTTPException) as exc_info:
        CalculationService().summarize_file(dummy_file)
    
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
    return CalculationService().summarize_file(csv_file)


def test_results_contain_usage_series_for_ranges():
    results = _results_for_days()

    assert list(results["usage_15min"]) == ["2024-05-01", "2024-05-02", "2024-05-03"]
    assert all(len(slots) == 96 and None not in slots for slots in results["usage_15min"].values())
    assert "slot_prices" not in results and "tariffs" not in results
    assert public_results(results).keys() == {
        "total_usage_kwh", "chart_15min", "chart_hourly", "chart_daily", "statistics",
    }


def test_full_range_matches_import_results():
    results = _results_for_days()

    ranged = _for_range(results, date(2024, 5, 1), date(2024, 5, 3))

    assert ranged == public_results(results)


def test_range_limits_charts_totals_and_statistics():
    results = _results_for_days()

    ranged = _for_range(results, date(2024, 5, 2), date(2024, 5, 3))

    assert [row["date"] for row in ranged["chart_daily"]] == ["2024-05-02", "2024-05-03"]
    assert ranged["total_usage_kwh"] == 120.0
    assert ranged["statistics"]["data_start"] == "2024-05-02"
    assert ranged["statistics"]["data_end"] == "2024-05-03"
    assert ranged["statistics"]["days_analyzed"] == 2
    assert ranged["statistics"]["records_count"] == 48


def test_range_end_date_is_inclusive():
    results = _results_for_days()

    ranged = _for_range(results, date(2024, 5, 2), date(2024, 5, 2))

    assert [row["date"] for row in ranged["chart_daily"]] == ["2024-05-02"]
    assert ranged["total_usage_kwh"] == 48.0


@pytest.mark.parametrize("chart, points", [("chart_hourly", 24), ("chart_15min", 96)])
def test_range_applies_to_every_resolution(chart, points):
    results = _results_for_days()

    first_day = _for_range(results, date(2024, 5, 1), date(2024, 5, 1))
    last_day = _for_range(results, date(2024, 5, 3), date(2024, 5, 3))

    # Profil doby liczony jest tylko z dni w zakresie: 1 kWh/h w pierwszym dniu, 3 kWh/h w ostatnim.
    per_point = 1.0 if chart == "chart_hourly" else 0.25
    assert len(first_day[chart]) == points
    assert {row["kwh"] for row in first_day[chart]} == {per_point}
    assert {row["kwh"] for row in last_day[chart]} == {round(per_point * 3, 2)}


def test_range_without_data_returns_empty_results():
    results = _results_for_days()

    ranged = _for_range(results, date(2024, 6, 1), date(2024, 6, 30))

    assert ranged["chart_daily"] == [] and ranged["chart_hourly"] == [] and ranged["chart_15min"] == []
    assert ranged["total_usage_kwh"] == 0.0 and "tariffs" not in ranged
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


def test_chart_prices_leave_days_without_price_empty():
    usage = {"2025-01-01": _day(0.25), "2025-01-02": _day(0.25)}
    slot_prices = {"G11-dynamic": {"type": "dynamiczna", "prices_by_day": {"2025-01-01": [2.0] * 96}}}

    summary = CalculationService.summarize_usage(usage, slot_prices)

    # dzień bez cen to null na wykresie (nie 0 PLN), a profil godzinowy liczy się tylko z dni z ceną
    second_day = next(row for row in summary["chart_daily"] if row["date"] == "2025-01-02")
    assert second_day["cost_G11-dynamic"] is None and second_day["price_G11-dynamic"] is None
    assert {row["cost_G11-dynamic"] for row in summary["chart_hourly"]} == {2.0}
    assert {row["price_G11-dynamic"] for row in summary["chart_hourly"]} == {2.0}
    assert "tariffs" not in summary
    # NaN nie jest poprawnym JSON-em - w żadnym wykresie nie może go być
    for chart in ("chart_15min", "chart_hourly", "chart_daily"):
        assert not any(
            isinstance(value, float) and math.isnan(value) for row in summary[chart] for value in row.values()
        )


METER_HEADER = "Data i godzina;Wartosc[kWh/kvar];Rodzaj energii"
SIMPLE_HEADER = "Data;Wartość kWh;Rodzaj"


def _import_dates(header, dates):
    """Importuje plik z odczytem 1 kWh dla każdej podanej daty i zwraca dni z pomiarami."""
    rows = "\n".join(f"{value};1,0;pobór" for value in dates)
    results = CalculationService().summarize_file(BytesIO(f"{header}\n{rows}".encode("utf-8")))
    days = [day for day, slots in results["usage_15min"].items() if any(kwh is not None for kwh in slots)]
    return days, results["statistics"]


@pytest.mark.parametrize("header", [METER_HEADER, SIMPLE_HEADER], ids=["kolumny-licznika", "kolumny-proste"])
@pytest.mark.parametrize(
    "dates, expected_days",
    [
        # Plik z licznika zapisany ponownie w Excelu - wcześniej 2025-02-12 stawało się 2 grudnia.
        (["2025-02-01 01:00", "2025-02-03 01:00", "2025-02-12 01:00"], ["2025-02-01", "2025-02-03", "2025-02-12"]),
        (["2025-2-3 1:00", "2025-02-12 01:00:00", "2025-02-13T01:00"], ["2025-02-03", "2025-02-12", "2025-02-13"]),
        (["02.01.2025 01:00", "13.06.2025 01:00"], ["2025-01-02", "2025-06-13"]),
        (["2.1.2025 1:00", "03.01.2025 01:00:00"], ["2025-01-02", "2025-01-03"]),
        (["02/01/2025 01:00", "02-01-2025 02:00"], ["2025-01-02"]),
        # Same niejednoznaczne daty (obie liczby <= 12) - polski układ, dzień pierwszy.
        (["05.03.2025 01:00", "06.03.2025 01:00"], ["2025-03-05", "2025-03-06"]),
        # Układ MM/DD rozpoznany po dacie, w której druga liczba jest > 12.
        (["03/05/2025 01:00", "03/13/2025 01:00"], ["2025-03-05", "2025-03-13"]),
    ],
    ids=["iso", "iso-warianty", "dd.mm", "dd.mm-bez-zer-i-sekundy", "dd/mm-i-dd-mm", "niejednoznaczne", "mm/dd"],
)
def test_import_recognizes_date_format_by_value(header, dates, expected_days):
    days, _ = _import_dates(header, dates)

    assert days == expected_days


@pytest.mark.parametrize(
    "dates",
    [["2025-02-12 24:00"], ["12.02.2025 24:00"], ["12.02.2025 24:00:00"]],
    ids=["iso", "dd.mm", "z-sekundami"],
)
def test_import_midnight_24_belongs_to_the_same_day(dates):
    days, statistics = _import_dates(METER_HEADER, dates)

    assert days == ["2025-02-12"]
    assert statistics["data_start"] == statistics["data_end"] == "2025-02-12"


def test_import_mixed_date_formats_in_one_file():
    # 45700 = 2025-02-12 00:00 w numeracji Excela, czyli odczyt z końca doby 11.02.
    days, _ = _import_dates(METER_HEADER, ["2025-02-10 01:00", "10.02.2025 02:00", "45700"])

    assert days == ["2025-02-10", "2025-02-11"]


def test_import_skips_rows_with_unrecognized_dates():
    days, statistics = _import_dates(METER_HEADER, ["2025-02-10 01:00", "jutro rano", "2025-02-11 01:00"])

    assert days == ["2025-02-10", "2025-02-11"]
    assert statistics["records_count"] == 2


def test_import_without_any_recognized_date_raises_422():
    with pytest.raises(HTTPException) as exc_info:
        _import_dates(METER_HEADER, ["jutro rano", "wczoraj"])

    assert exc_info.value.status_code == 422
    assert "Nie rozpoznano formatu dat" in exc_info.value.detail


def _import_rows(rows, header=SIMPLE_HEADER):
    lines = "\n".join(f"{timestamp};{str(kwh).replace('.', ',')};pobór" for timestamp, kwh in rows)
    content = f"{header}\n{lines}".encode("utf-8")
    return CalculationService().summarize_file(BytesIO(content))


def _quarter_rows(day, values):
    rows = []
    for index, kwh in enumerate(values):
        minutes = (index + 1) * 15
        rows.append((f"{day} {minutes // 60:02d}:{minutes % 60:02d}", kwh))
    return rows


def test_quarter_hour_file_keeps_each_reading_in_its_own_slot():
    values = [round(0.01 * (slot + 1), 2) for slot in range(96)]

    results = _import_rows(_quarter_rows("2025-01-01", values))

    assert list(results["usage_15min"]) == ["2025-01-01"]
    assert results["usage_15min"]["2025-01-01"] == values
    assert results["statistics"]["resolution_minutes"] == 15
    assert results["statistics"]["records_count"] == 96
    assert results["statistics"]["has_missing_data"] is False
    assert results["total_usage_kwh"] == round(sum(values), 2)


def test_hourly_file_is_still_split_into_four_quarters():
    rows = [(f"2025-01-01 {hour}:00", 2.0) for hour in range(1, 25)]

    results = _import_rows(rows)

    assert results["usage_15min"]["2025-01-01"] == [0.5] * 96
    assert results["statistics"]["resolution_minutes"] == 60
    assert results["statistics"]["records_count"] == 24
    assert results["total_usage_kwh"] == 48.0


def test_quarter_hour_file_in_meter_format_with_midnight_24():
    rows = [("01.01.2025 23:45", 1.0), ("01.01.2025 24:00", 2.0)]

    results = _import_rows(rows, header=METER_HEADER)

    day = results["usage_15min"]["2025-01-01"]
    assert day[94] == 1.0 and day[95] == 2.0
    assert results["statistics"]["resolution_minutes"] == 15


@pytest.mark.parametrize(
    "rows, expected",
    [
        ([("2025-01-01 01:00", 1), ("2025-01-01 05:00", 1), ("2025-01-03 01:00", 1)], 60),
        ([("2025-01-01 00:15", 1), ("2025-01-01 03:00", 1), ("2025-01-01 03:15", 1)], 15),
        ([("2025-10-26 02:00", 1), ("2025-10-26 02:00", 1), ("2025-10-26 03:00", 1)], 60),
        ([("2025-01-01 01:00", 1)], 60),
    ],
    ids=["godzinowy-z-lukami", "kwadransowy-z-lukami", "zmiana-czasu", "jeden-odczyt"],
)
def test_resolution_detection(rows, expected):
    assert _import_rows(rows)["statistics"]["resolution_minutes"] == expected


def test_resolution_detection_handles_imprecise_excel_times():
    rows = [(f"{45658 + hour / 24}", 1.0) for hour in range(1, 4)]

    results = _import_rows(rows, header=METER_HEADER)

    assert results["statistics"]["resolution_minutes"] == 60
    assert results["usage_15min"]["2025-01-01"][:12] == [0.25] * 12


@pytest.mark.parametrize(
    "rows",
    [
        [("2025-01-01 00:30", 1), ("2025-01-01 01:00", 1), ("2025-01-01 01:30", 1)],
        [("2025-01-01 01:00", 1), ("2025-01-01 02:30", 1)],
    ],
    ids=["co-30-min", "nieregularne"],
)
def test_unsupported_resolution_raises_422(rows):
    with pytest.raises(HTTPException) as exc_info:
        _import_rows(rows)

    assert exc_info.value.status_code == 422
    assert "Nieobsługiwana rozdzielczość" in exc_info.value.detail


def test_range_on_quarter_hour_file_counts_quarter_records():
    rows = _quarter_rows("2025-01-01", [0.25] * 96) + _quarter_rows("2025-01-02", [0.5] * 96)
    results = _import_rows(rows)

    ranged = _for_range(results, date(2025, 1, 2), date(2025, 1, 2))

    assert ranged["statistics"]["resolution_minutes"] == 15
    assert ranged["statistics"]["records_count"] == 96
    assert ranged["total_usage_kwh"] == 48.0


def test_range_on_results_without_resolution_assumes_hourly():
    results = _results_for_days()
    del results["statistics"]["resolution_minutes"]

    ranged = _for_range(results, date(2024, 5, 1), date(2024, 5, 1))

    assert ranged["statistics"]["records_count"] == 24
    assert ranged["statistics"]["resolution_minutes"] == 60


def test_summary_of_mixed_resolutions_has_no_records_count():
    usage = {"2025-01-01": [0.25] * 96}

    summary = CalculationService.summarize_usage(usage, {}, None)

    assert summary["statistics"]["records_count"] is None
    assert summary["statistics"]["resolution_minutes"] is None


DEVICES_DEMO_FILE = Path(__file__).parent / "fixtures" / "devices_demo_30d.json"


def _devices_demo_results():
    with DEVICES_DEMO_FILE.open("rb") as handle:
        return CalculationService().summarize_file(handle)


def test_devices_file_counts_actions_as_records():
    results = _devices_demo_results()

    actions_count = results["import_report"]["rows_imported"]
    assert results["statistics"]["records_count"] == actions_count
    assert results["statistics"]["data_source"] == "devices"
    assert sum(results["actions_per_day"].values()) == actions_count
    assert "actions_per_day" not in public_results(results)


def test_devices_file_range_counts_actions_of_selected_days():
    results = _devices_demo_results()
    day = date(2026, 10, 25)

    in_range = _for_range(results, day, day)

    assert in_range["statistics"]["records_count"] == results["actions_per_day"]["2026-10-25"]
    assert in_range["statistics"]["data_source"] == "devices"


def test_meter_file_counts_readings_as_records():
    results = _results_for_days()

    assert results["statistics"]["data_source"] == "meter"
    assert "actions_per_day" not in results


def _covering(*usages):
    return CalculationService.device_coverage(list(usages))


def test_device_contributions_of_files_with_different_devices():
    day = {"2026-01-05": _day(0.0)}

    contributions = CalculationService.device_contributions([{"kitchen"}, {"garage"}], _covering(day, day))

    assert contributions == [{"days_used": 1, "slots_used": 96}, {"days_used": 1, "slots_used": 96}]


def test_device_contributions_newer_file_takes_only_its_slots():
    whole_day = {"2026-01-05": _day(0.0)}
    afternoon = {"2026-01-05": _day(0.0, slots=range(48, 96))}

    contributions = CalculationService.device_contributions([{"dev"}, {"dev"}], _covering(whole_day, afternoon))

    assert [item["slots_used"] for item in contributions] == [48, 48]


def test_device_contributions_duplicate_file_takes_everything():
    day = {"2026-01-05": _day(0.0)}

    contributions = CalculationService.device_contributions([{"dev"}, {"dev"}], _covering(day, day))

    assert contributions == [{"days_used": 0, "slots_used": 0}, {"days_used": 1, "slots_used": 96}]


def test_device_usage_series_has_zero_in_covered_slots_without_devices():
    covering = _covering({"2026-01-05": _day(0.0, slots=range(48, 96))})

    usage = CalculationService.device_usage_series(covering, [("2026-01-05", 60, 1.5)])

    assert usage["2026-01-05"][:48] == [None] * 48
    assert usage["2026-01-05"][48] == 0.0
    assert usage["2026-01-05"][60] == 1.5


def test_incomplete_days_respect_daylight_saving_change():
    full_day = [0.1] * 96
    spring_change = [None if 8 <= slot < 12 else 0.1 for slot in range(96)]
    gap = [None if slot == 40 else 0.1 for slot in range(96)]
    spring_change_with_gap = [None if slot == 40 else value for slot, value in enumerate(spring_change)]

    usage = {
        "2026-03-28": full_day,
        "2026-03-29": spring_change,
        "2026-03-30": gap,
        "2026-10-25": full_day,
        "2027-03-28": spring_change_with_gap,
    }
    statistics = CalculationService.summarize_usage(usage, {})["statistics"]

    assert statistics["incomplete_days"] == ["2026-03-30", "2027-03-28"]
    assert statistics["has_missing_data"] is True

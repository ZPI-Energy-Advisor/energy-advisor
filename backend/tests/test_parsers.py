import json
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from fastapi import HTTPException

from app import parsers
from app.parsers import (
    KWH,
    TIMESTAMP_START,
    UNIT_ACTION,
    DeviceRecord,
    DevicesJsonParser,
    DocumentParser,
    EnergyFileParser,
    FileImportError,
    ImportReport,
    ParsedEnergyFile,
    detect_document_parser,
    detect_parser,
    parse_energy_file,
    read_document,
    read_table,
)
from app.parsers.base import SkippedRow
from app.parsers.formats import MeterExportParser, SimpleCsvParser, TauronV1Parser, TauronV2Parser
from app.services.calculation_service import CalculationService, public_results


FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_DEVICES_FILE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "samples" / "devices-example.json"
DEMO_DEVICES_FILE = FIXTURES / "devices_demo_30d.json"
TAURON_HEADER = "Nr platnika;Nr punktu poboru energii;Rodzaj energii;Data i godzina;Strefa;Wartosc[kWh/kvar];Kompletnosc[%]"
SIMPLE_HEADER = "Data;Wartość kWh;Rodzaj"


def _row(date, kwh="0,500", kind="energia czynna pobrana"):
    return f"12345678;PPE:1;{kind};{date};Cała doba;{kwh};100"


def _day(prefix="01.01.2025", hours=range(1, 25), **kwargs):
    return [_row(f"{prefix} {hour:02d}:00", **kwargs) for hour in hours]


def _file(lines, encoding="windows-1250"):
    return BytesIO("\r\n".join(lines).encode(encoding))


def _parse(lines, **kwargs):
    return parse_energy_file(_file(lines, **kwargs))


def _import_error(content):
    with pytest.raises(FileImportError) as exc_info:
        parse_energy_file(content if isinstance(content, BytesIO) else _file(content))
    return exc_info.value


def _repository():
    tariff = MagicMock()
    tariff.id, tariff.name, tariff.type = 1, "G11", "stala"
    rate = MagicMock()
    rate.time_start = datetime.strptime("00:00:00", "%H:%M:%S").time()
    rate.time_end = datetime.strptime("23:59:59", "%H:%M:%S").time()
    rate.price_per_kwh = 1.0
    repository = MagicMock()
    repository.get_all.return_value = [tariff]
    repository.get_rates_for_tariff.return_value = [rate]
    return repository


@pytest.mark.parametrize(
    "fixture, parser, first_start, last_start",
    [
        ("tauron_v1_daty_dd_mm_rrrr.csv", TauronV1Parser, "2025-06-13 00:00", "2025-06-14 23:00"),
        ("tauron_v2_daty_rrrr_mm_dd.csv", TauronV2Parser, "2025-01-01 00:00", "2025-01-02 23:00"),
    ],
    ids=["tauron-v1", "tauron-v2"],
)
def test_parse_both_tauron_exports(fixture, parser, first_start, last_start):
    with open(FIXTURES / fixture, "rb") as handle:
        parsed = parse_energy_file(handle)

    assert parsed.report.detected_format == parser.name
    assert parsed.report.format_label == parser.label
    assert parsed.resolution_minutes == 60
    assert parsed.report.rows_total == parsed.report.rows_imported == 48
    assert parsed.report.skipped_count == 0
    assert parsed.data[TIMESTAMP_START].iloc[0] == pd.Timestamp(first_start)
    assert parsed.data[TIMESTAMP_START].iloc[-1] == pd.Timestamp(last_start)
    assert parsed.data[KWH].sum() == pytest.approx(19.92)


def test_parse_meter_export_with_zone_and_status_columns():
    with open(FIXTURES / "odczyty_licznika.csv", "rb") as handle:
        parsed = parse_energy_file(handle)

    assert parsed.report.detected_format == MeterExportParser.name
    assert parsed.resolution_minutes == 60
    assert parsed.report.rows_total == 96
    assert parsed.report.rows_imported == 48
    assert parsed.report.rows_ignored == 48
    assert parsed.report.skipped_count == 0
    assert parsed.data[TIMESTAMP_START].iloc[0] == pd.Timestamp("2026-10-01 00:00")
    assert parsed.data[TIMESTAMP_START].iloc[-1] == pd.Timestamp("2026-10-02 23:00")
    assert parsed.data[KWH].sum() == pytest.approx(19.92)


@pytest.mark.parametrize(
    "lines, expected",
    [
        ([TAURON_HEADER, _row("01.01.2025 01:00")], TauronV1Parser),
        ([TAURON_HEADER, _row("2025-01-01 01:00")], TauronV2Parser),
        ([TAURON_HEADER.upper(), _row("2025-01-01 01:00")], TauronV2Parser),
        (["Data i godzina;Wartosc[kWh/kvar];Rodzaj energii", "01.01.2025 01:00;0,5;pobór"], TauronV1Parser),
        ([SIMPLE_HEADER, "2025-01-01 01:00;0,5;pobór"], SimpleCsvParser),
    ],
    ids=["daty-dd-mm", "daty-iso", "naglowek-wielkimi-literami", "minimalne-kolumny", "prosty-csv"],
)
def test_detect_parser(lines, expected):
    assert isinstance(detect_parser(read_table(_file(lines))), expected)


@pytest.mark.parametrize(
    "lines",
    [["Data;Wartość kWh", "2025-01-01 01:00;1"], ["Totalna;Bzdura", "1;2"]],
    ids=["brak-kolumny-rodzaj", "obce-kolumny"],
)
def test_unknown_columns_are_rejected(lines):
    error = _import_error(lines)

    assert error.status_code == 422
    assert "Nierozpoznany format" in error.detail


def test_parse_quarter_hour_tauron_export():
    parsed = _parse([TAURON_HEADER, _row("01.01.2025 00:15"), _row("01.01.2025 00:30"), _row("01.01.2025 24:00")])

    assert parsed.resolution_minutes == 15
    assert parsed.data[TIMESTAMP_START].tolist() == [
        pd.Timestamp("2025-01-01 00:00"),
        pd.Timestamp("2025-01-01 00:15"),
        pd.Timestamp("2025-01-01 23:45"),
    ]


@pytest.mark.parametrize(
    "lines, encoding",
    [
        ([TAURON_HEADER, *_day()], "utf-8"),
        (["﻿" + TAURON_HEADER, *_day()], "utf-8"),
        ([TAURON_HEADER.replace(";", "\t"), *[line.replace(";", "\t") for line in _day()]], "windows-1250"),
        (
            [TAURON_HEADER.replace(";", ","), *[line.replace(";", ",").replace("0,500", "0.500") for line in _day()]],
            "windows-1250",
        ),
        ([" ; ".join(TAURON_HEADER.split(";")), *_day()], "windows-1250"),
        ([TAURON_HEADER, *_day(kwh='"0,500"')], "windows-1250"),
        ([TAURON_HEADER, *_day(kwh="0.500")], "windows-1250"),
        ([TAURON_HEADER, *reversed(_day())], "windows-1250"),
        ([TAURON_HEADER, *[_row(f"01.01.2025 {hour:02d}:00:00") for hour in range(1, 25)]], "windows-1250"),
        ([TAURON_HEADER, *_day(), TAURON_HEADER, *_day("02.01.2025")[:0]], "windows-1250"),
    ],
    ids=[
        "utf-8", "utf-8-z-bom", "tabulator", "przecinek-z-kropka-dziesietna", "spacje-w-naglowku",
        "cudzyslowy", "kropka-dziesietna", "odwrocona-kolejnosc", "sekundy", "powtorzony-naglowek",
    ],
)
def test_variants_of_valid_file_import_the_same_day(lines, encoding):
    parsed = _parse(lines, encoding=encoding)

    assert parsed.report.rows_imported == 24
    assert parsed.report.skipped_count == 0
    assert parsed.data[KWH].sum() == pytest.approx(12.0)


def test_concatenated_exports_are_joined_and_repeated_header_is_not_a_row():
    report = _parse([TAURON_HEADER, *_day(), TAURON_HEADER, *_day("02.01.2025")]).report

    assert report.rows_total == report.rows_imported == 48


def test_numbers_with_thousands_separator():
    parsed = _parse([TAURON_HEADER, _row("01.01.2025 01:00", kwh="1 234,500"), _row("01.01.2025 02:00", kwh="1 000")])

    assert parsed.data[KWH].tolist() == [1234.5, 1000.0]


def test_rows_with_wrong_number_of_columns_are_reported_not_fatal():
    lines = [
        TAURON_HEADER,
        *_day(hours=range(1, 12)),
        "12345678;PPE:1;energia czynna pobrana;01.01.2025 12:00",
        _row("01.01.2025 13:00") + ";;nadmiarowa",
        _row("01.01.2025 14:00") + ";",
        *_day(hours=range(15, 25)),
    ]

    report = _parse(lines).report

    assert report.rows_imported == 22
    assert [(item.row, item.reason) for item in report.skipped_examples] == [
        (13, "nieprawidłowa liczba kolumn (4 zamiast 7)"),
        (14, "nieprawidłowa liczba kolumn (9 zamiast 7)"),
    ]


def test_same_export_twice_in_one_file_is_not_double_counted():
    parsed = _parse([TAURON_HEADER, *_day(), *_day()])

    assert parsed.data[KWH].sum() == pytest.approx(12.0)
    assert parsed.report.skipped_count == 24
    assert parsed.report.skipped_examples[0].row == 26
    assert parsed.report.skipped_examples[0].reason == "powtórzony odczyt (taki sam jak w wierszu 2)"


def test_same_timestamp_with_different_values_is_kept():
    parsed = _parse([TAURON_HEADER, _row("26.10.2025 02:00", kwh="0,4"), _row("26.10.2025 02:00", kwh="0,6"), _row("26.10.2025 03:00")])

    assert parsed.report.rows_imported == 3
    assert parsed.data[KWH].sum() == pytest.approx(1.5)


def test_parse_reports_skipped_and_ignored_rows():
    lines = [
        TAURON_HEADER,
        _row("01.01.2025 01:00", kwh="1,0"),
        _row("01.01.2025 02:00", kwh="abc"),
        _row("jutro rano", kwh="1,0"),
        _row("", kwh="1,0"),
        _row("01.01.2025 03:00", kwh="5,0", kind="energia czynna oddana"),
        "",
        _row("01.01.2025 04:00", kwh="-0,5"),
        _row("01.01.2025 05:00", kwh="1,0"),
        _row("01.01.2025", kwh="1,0"),
        ";;;Suma;;12,000;",
    ]

    report = _parse(lines).report

    assert report.rows_total == 9
    assert report.rows_imported == 2
    assert report.rows_ignored == 1
    assert [(item.row, item.reason) for item in report.skipped_examples] == [
        (3, "nieprawidłowa wartość zużycia: „abc”"),
        (4, "nieprawidłowa data: „jutro rano”"),
        (5, "brak daty, wartości lub rodzaju energii"),
        (8, "ujemna wartość zużycia: „-0,5”"),
        (10, "nieprawidłowa data: „01.01.2025”"),
        (11, "brak daty, wartości lub rodzaju energii"),
    ]


def test_parse_limits_skipped_examples_to_ten():
    lines = [TAURON_HEADER, _row("01.01.2025 01:00")] + [_row(f"01.01.2025 {hour:02d}:00", kwh="x") for hour in range(2, 17)]

    report = _parse(lines).report

    assert report.skipped_count == 15
    assert [item.row for item in report.skipped_examples] == list(range(3, 13))


def test_report_to_dict():
    report = _parse([TAURON_HEADER, _row("01.01.2025 01:00"), _row("01.01.2025 02:00", kwh="x")]).report

    assert report.to_dict() == {
        "detected_format": "tauron_v1",
        "format_label": TauronV1Parser.label,
        "rows_total": 2,
        "rows_imported": 1,
        "rows_ignored": 0,
        "resolution_minutes": 60,
        "unit": "row",
        "skipped_rows": {"count": 1, "examples": [{"row": 3, "reason": "nieprawidłowa wartość zużycia: „x”"}]},
    }


def test_report_describes_skipped_actions_with_action_id():
    report = ImportReport(
        "devices", DevicesJsonParser.label, unit=UNIT_ACTION, skipped_count=1,
        skipped_examples=[SkippedRow(row=5, reason="akcje nakładają się", action_id="act_0016")],
    )

    assert report.to_dict()["unit"] == "action"
    assert report.to_dict()["skipped_rows"]["examples"] == [
        {"row": 5, "reason": "akcje nakładają się", "action_id": "act_0016"}
    ]


def _xlsx_bytes():
    content = BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return BytesIO(content.getvalue())


@pytest.mark.parametrize(
    "content, status, message",
    [
        (_xlsx_bytes(), 400, "To jest plik Excel"),
        (BytesIO(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4), 400, "nie jest plikiem tekstowym CSV"),
        (BytesIO(b""), 400, "Plik jest pusty"),
        (BytesIO(b"\r\n\r\n"), 400, "Plik jest pusty"),
        ([TAURON_HEADER], 400, "nie zawiera żadnych odczytów"),
        ([TAURON_HEADER, *_day(kind="energia czynna oddana")], 400, "tylko dane o oddaniu"),
        ([TAURON_HEADER, *_day(kwh="-0,500")], 422, "Żaden wiersz z poborem energii nie ma poprawnej wartości"),
        ([TAURON_HEADER, *_day(kwh="brak")], 422, "np. wiersz 2: nieprawidłowa wartość zużycia: „brak”"),
        ([TAURON_HEADER.replace(";", ","), *[line.replace(";", ",") for line in _day()]], 422, "Nie udało się odczytać żadnego wiersza"),
        ([TAURON_HEADER, *[_row(f"{day:02d}.01.2025") for day in range(1, 8)]], 422, "Nie rozpoznano formatu dat"),
        ([TAURON_HEADER, _row("01.01.2025 00:30"), _row("01.01.2025 01:00")], 422, "Nieobsługiwana rozdzielczość"),
    ],
    ids=[
        "xlsx", "obrazek", "pusty-plik", "same-puste-linie", "tylko-naglowek", "tylko-oddanie",
        "same-ujemne", "same-zle-wartosci", "przecinek-z-przecinkiem-dziesietnym", "daty-bez-godziny", "co-30-min",
    ],
)
def test_invalid_files(content, status, message):
    error = _import_error(content)

    assert error.status_code == status
    assert message in error.detail


def test_calculation_accepts_parsed_data_without_csv():
    parsed = ParsedEnergyFile(
        data=pd.DataFrame({TIMESTAMP_START: [pd.Timestamp("2025-01-01 00:00")], KWH: [2.0]}),
        resolution_minutes=60,
        report=ImportReport(detected_format="test", format_label="test"),
    )

    results = CalculationService(_repository()).calculate(parsed)

    assert results["usage_15min"]["2025-01-01"][:4] == [0.5] * 4
    assert results["tariffs"]["G11"]["total_usage_kwh"] == 2.0
    assert results["statistics"]["records_count"] == 1


class _TestFormatParser(EnergyFileParser):
    name = "testowy"
    label = "Format testowy"

    def detect(self, table):
        return list(table.columns) == ["koniec", "kwh"]

    def parse(self, table):
        data = pd.DataFrame({
            TIMESTAMP_START: pd.to_datetime(table["koniec"]) - pd.Timedelta(hours=1),
            KWH: table["kwh"].astype(float),
        }).reset_index(drop=True)
        report = ImportReport(self.name, self.label, rows_total=len(table), rows_imported=len(data), resolution_minutes=60)
        return ParsedEnergyFile(data=data, resolution_minutes=60, report=report)


def test_new_format_needs_only_a_registered_parser(monkeypatch):
    monkeypatch.setattr(parsers, "PARSERS", [_TestFormatParser(), *parsers.PARSERS])

    results = CalculationService(_repository()).calculate_all_tariffs(_file(["koniec;kwh", "2025-01-01 01:00;4"]))

    assert results["import_report"]["detected_format"] == "testowy"
    assert results["tariffs"]["G11"]["total_usage_kwh"] == 4.0


def test_calculate_all_tariffs_adds_report_and_hides_it_from_public_results():
    results = CalculationService(_repository()).calculate_all_tariffs(_file([TAURON_HEADER, _row("2025-01-01 01:00")]))

    assert results["import_report"]["detected_format"] == "tauron_v2"
    assert "import_report" not in public_results(results)


def test_calculate_all_tariffs_turns_import_errors_into_http_errors():
    with pytest.raises(HTTPException) as exc_info:
        CalculationService(_repository()).calculate_all_tariffs(_file(["Totalna;Bzdura", "1;2"]))

    assert exc_info.value.status_code == 422


@pytest.mark.parametrize("path", [SAMPLE_DEVICES_FILE, DEMO_DEVICES_FILE], ids=["plik-przykladowy", "plik-demo-30-dni"])
def test_devices_file_goes_to_devices_parser(path):
    with path.open("rb") as handle:
        assert isinstance(detect_document_parser(read_document(handle)), DevicesJsonParser)
        with pytest.raises(FileImportError) as exc_info:
            parse_energy_file(handle)

    assert exc_info.value.status_code == 422
    assert "będzie dostępny wkrótce" in exc_info.value.detail


def test_json_is_recognized_by_content_despite_bom_and_whitespace():
    content = BytesIO(b'\xef\xbb\xbf \r\n {"devices": [], "energy_usage": []}')

    assert read_document(content) == {"devices": [], "energy_usage": []}


@pytest.mark.parametrize("lines, encoding", [
    ([TAURON_HEADER, _row("2025-01-01 01:00")], "windows-1250"),
    ([SIMPLE_HEADER, "2025-01-01 01:00;0,5;pobór"], "utf-8"),
], ids=["tauron-windows-1250", "prosty-csv-utf-8"])
def test_csv_files_do_not_go_to_document_parsers(lines, encoding):
    assert read_document(_file(lines, encoding=encoding)) is None


@pytest.mark.parametrize(
    "content, status, message",
    [
        (b'{"devices": [', 400, "Niepoprawny plik JSON: Expecting value (linia 1, kolumna 14)"),
        (b'{"readings": []}', 422, "Nierozpoznany format pliku JSON"),
    ],
    ids=["uciety-json", "json-bez-pol-urzadzen"],
)
def test_invalid_json_files(content, status, message):
    error = _import_error(BytesIO(content))

    assert error.status_code == status
    assert message in error.detail


class _TestDocumentParser(DocumentParser):
    name = "dokument_testowy"
    label = "Dokument testowy"

    def detect(self, document):
        return "readings" in document

    def parse(self, document):
        data = pd.DataFrame({
            TIMESTAMP_START: [pd.Timestamp(reading["start"]) for reading in document["readings"]],
            KWH: [float(reading["kwh"]) for reading in document["readings"]],
        })
        report = ImportReport(self.name, self.label, rows_total=len(data), rows_imported=len(data),
                              resolution_minutes=60, unit=UNIT_ACTION)
        device = DeviceRecord(device_id="dev_01", name="Urządzenie", device_type="other",
                              device_category="Inne", flexibility_mode="fixed")
        return ParsedEnergyFile(data=data, resolution_minutes=60, report=report, devices=[device])


def test_new_document_format_needs_only_a_registered_parser(monkeypatch):
    monkeypatch.setattr(parsers, "DOCUMENT_PARSERS", [_TestDocumentParser(), *parsers.DOCUMENT_PARSERS])
    content = BytesIO(json.dumps({"readings": [{"start": "2025-01-01 00:00", "kwh": 4}]}).encode())

    results = CalculationService(_repository()).calculate_all_tariffs(content)

    assert results["import_report"]["detected_format"] == "dokument_testowy"
    assert results["import_report"]["unit"] == "action"
    assert results["tariffs"]["G11"]["total_usage_kwh"] == 4.0

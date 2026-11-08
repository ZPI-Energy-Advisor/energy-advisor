"""Ładowanie cennika: skrypt `load_tariffs.py`, odrzucanie błędnych plików i zapis do bazy (bez commitu)."""

import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.NewModels import RegulatoryPeriod, TariffDefinition, UnsupportedTariff
from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum
from app.tariff_data.build import build_definitions, build_unsupported
from app.tariff_data.db import _definition, load_data_set
from app.tariff_data.files import TariffDataError, read_data_set
from tariff_compare import database_mismatches

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tariffs" / "valid" / "2030"
DATA_DIR = BACKEND_DIR / "data" / "tariffs"
PGE = DistributionOperatorEnum.PGE

_spec = importlib.util.spec_from_file_location("load_tariffs_script", BACKEND_DIR / "scripts" / "load_tariffs.py")
load_tariffs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load_tariffs)


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _write(directory: Path, name: str, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _errors_of(path: Path | list[Path]) -> str:
    paths = path if isinstance(path, list) else [path]
    with pytest.raises(TariffDataError) as caught:
        read_data_set(paths)
    return "\n".join(caught.value.errors)


# ---------------------------------------------------------------- skrypt


def test_load_script_check_accepts_valid_fixture(capsys):
    assert load_tariffs.main(["--check", str(FIXTURE_DIR)]) == 0
    output = capsys.readouterr().out
    assert "Pliki poprawne: 1 operatorów, 1 opłat regulacyjnych." in output
    assert "PGE" in output and "G12w" in output


def test_load_script_check_rejects_broken_file(tmp_path, capsys):
    data = _fixture_json("pge.json")
    data["distribution"][0]["tariffs"]["G11"]["hours"][0]["intervals"] = [["00:00", "23:00"]]
    path = _write(tmp_path / "2030", "pge.json", data)
    assert load_tariffs.main(["--check", str(path)]) == 1
    assert "brak strefy 23:00–24:00" in capsys.readouterr().err


def test_load_script_complete_check_fails_when_fixture_does_not_cover_supported_period(capsys):
    assert load_tariffs.main(["--check", "--complete", str(FIXTURE_DIR)]) == 1
    assert "Niepełne pokrycie dni" in capsys.readouterr().err


# ---------------------------------------------------------------- błędne pliki


def _broken_operator(tmp_path, mutate) -> Path:
    data = _fixture_json("pge.json")
    mutate(data)
    return _write(tmp_path / "2030", "pge.json", data)


def test_rejects_hour_gap(tmp_path):
    def mutate(data):
        data["distribution"][0]["tariffs"]["G11"]["hours"][0]["intervals"] = [["00:00", "23:00"]]

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "godziny G11" in message
    assert "brak strefy 23:00–24:00" in message


def test_rejects_hour_overlap(tmp_path):
    def mutate(data):
        hours = data["distribution"][0]["tariffs"]["G12"]["hours"]
        hours[0]["intervals"] = [["06:00", "16:00"], ["17:00", "22:00"]]  # nakłada się na strefę 2 (15–17)

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "godziny G12" in message
    assert "strefy nakładają się 15:00–16:00" in message


def test_rejects_tariff_with_distribution_but_no_energy_for_part_of_period(tmp_path):
    def mutate(data):
        del data["energy"][1]["tariffs"]["G12w"]  # od 1.10 brak cen energii G12w; G11 i G12 mają

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "taryfa G12w: są stawki dystrybucji, a brak cen energii dla dni" in message
    assert "taryfa G11" not in message
    assert "taryfa G12:" not in message


def test_rejects_energy_without_distribution_for_part_of_period(tmp_path):
    def mutate(data):
        del data["distribution"][1]["tariffs"]["G12w"]

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "taryfa G12w: są ceny energii, a brak stawek dystrybucji dla dni" in message


def test_rejects_source_without_document_or_description(tmp_path):
    def mutate(data):
        data["distribution"][1]["subscription_source"] = {"page": "s. 1"}

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "źródło musi mieć dokument („doc”) i stronę („page”) albo opis („text”)." in message
    assert "distribution[1].subscription_source" in message


def test_rejects_unknown_document_key(tmp_path):
    def mutate(data):
        data["distribution"][0]["tariffs"]["G11"]["rates_source"]["doc"] = "nieistniejacy"

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "nieznany dokument „nieistniejacy”" in message
    assert "distribution[0].tariffs.G11.rates_source" in message


def test_rejects_entry_outside_covers(tmp_path):
    def mutate(data):
        data["distribution"][1]["valid_to"] = "2031-01-31"

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "distribution[1]" in message
    assert "wychodzi poza zakres pliku 2030-01-01 – 2030-12-31" in message


def test_rejects_two_overlapping_entries_of_the_same_tariff(tmp_path):
    def mutate(data):
        data["distribution"][0]["valid_to"] = "2030-07-15"

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "taryfa G11" in message
    assert "nakłada się na" in message
    assert "distribution[0]" in message and "distribution[1]" in message


def test_rejects_zone_without_hours(tmp_path):
    def mutate(data):
        hours = data["distribution"][0]["tariffs"]["G12"]["hours"]
        data["distribution"][0]["tariffs"]["G12"]["hours"] = [rule for rule in hours if rule["zone"] == "1"]

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "strefa 2 ma stawki, ale nie ma godzin" in message


def test_rejects_regulatory_period_gap(tmp_path):
    data = _fixture_json("regulatory.json")
    data["periods"][0]["valid_to"] = "2030-06-29"
    path = _write(tmp_path / "2030", "regulatory.json", data)
    message = _errors_of(path)
    assert "brak opłat regulacyjnych dla dni" in message
    assert "2030-06-30" in message or "30.06.2030" in message


def test_rejects_two_files_of_one_operator_with_overlapping_covers(tmp_path):
    first = _write(tmp_path / "2030", "pge.json", _fixture_json("pge.json"))
    second = _write(tmp_path / "2030", "pge_kopia.json", _fixture_json("pge.json"))
    message = _errors_of([first, second])
    assert "PGE" in message
    assert "zakresy plików" in message and "nakładają się" in message


def test_reports_all_errors_at_once(tmp_path):
    def mutate(data):
        data["distribution"][0]["tariffs"]["G11"]["rates_source"]["doc"] = "nieistniejacy"
        data["distribution"][1]["valid_to"] = "2031-01-31"
        data["distribution"][0]["tariffs"]["G11"]["hours"][0]["intervals"] = [["00:00", "23:00"]]

    message = _errors_of(_broken_operator(tmp_path, mutate))
    assert "nieznany dokument" in message
    assert "poza zakres pliku" in message
    assert "brak strefy 23:00–24:00" in message


# ---------------------------------------------------------------- baza (bez commitu)


def _count_2030(db):
    return (
        db.query(TariffDefinition)
        .filter(TariffDefinition.osd_operator == PGE, TariffDefinition.valid_from >= date(2030, 1, 1),
                TariffDefinition.valid_from <= date(2030, 12, 31))
        .count(),
        db.query(UnsupportedTariff)
        .filter(UnsupportedTariff.osd_operator == PGE, UnsupportedTariff.valid_from >= date(2030, 1, 1),
                UnsupportedTariff.valid_from <= date(2030, 12, 31))
        .count(),
        db.query(RegulatoryPeriod)
        .filter(RegulatoryPeriod.valid_from >= date(2030, 1, 1), RegulatoryPeriod.valid_from <= date(2030, 12, 31))
        .count(),
    )


def test_load_fixture_creates_rows_equal_to_file(db):
    data_set = read_data_set([FIXTURE_DIR])
    summaries = load_data_set(db, data_set)
    db.flush()

    expected_definitions = build_definitions(data_set.operator_files[0])
    assert _count_2030(db) == (len(expected_definitions), 1, 2)
    by_name = {summary.file: summary for summary in summaries}
    assert by_name["2030/pge.json"].inserted == len(expected_definitions) + 1
    assert by_name["2030/regulatory.json"].inserted == 2
    assert database_mismatches(db, data_set) == []


def test_load_fixture_twice_gives_same_rows_without_duplicates(db):
    data_set = read_data_set([FIXTURE_DIR])
    load_data_set(db, data_set)
    db.flush()
    counts = _count_2030(db)
    first_ids = {row.id for row in db.query(TariffDefinition).filter(TariffDefinition.valid_from >= date(2030, 1, 1),
                                                                      TariffDefinition.valid_from <= date(2030, 12, 31))}

    summaries = load_data_set(db, data_set)
    db.flush()

    assert _count_2030(db) == counts
    assert all(summary.removed == summary.inserted for summary in summaries)
    assert database_mismatches(db, data_set) == []
    second_ids = {row.id for row in db.query(TariffDefinition).filter(TariffDefinition.valid_from >= date(2030, 1, 1),
                                                                       TariffDefinition.valid_from <= date(2030, 12, 31))}
    assert len(second_ids) == len(first_ids)


def test_load_modified_copy_replaces_values(db, tmp_path):
    load_data_set(db, read_data_set([FIXTURE_DIR]))
    db.flush()

    pge = _fixture_json("pge.json")
    pge["distribution"][0]["tariffs"]["G11"]["zones"]["1"]["rate"] = "0.3100"
    pge["energy"][0]["price_cap"] = "0.4800"
    del pge["unsupported"]
    regulatory = _fixture_json("regulatory.json")
    regulatory["periods"][0]["quality_fee_per_kwh"]["value"] = "0.0333"
    regulatory["periods"][0]["transition_fee_monthly"]["bands"][0]["fee"] = "0.05"
    directory = tmp_path / "2030"
    _write(directory, "pge.json", pge)
    _write(directory, "regulatory.json", regulatory)
    modified = read_data_set([directory])

    load_data_set(db, modified)
    db.flush()

    row = (
        db.query(TariffDefinition)
        .filter_by(osd_operator=PGE, tariff_code=TariffTypeEnum.G11, valid_from=date(2030, 1, 1))
        .one()
    )
    assert row.variable_network_rates[0].rate_per_kwh_net_pln == Decimal("0.3100")
    assert row.energy_price_cap_per_kwh == Decimal("0.4800")
    assert _count_2030(db)[1] == 0  # taryfa nieliczona zniknęła razem z wpisem w pliku
    period = db.query(RegulatoryPeriod).filter_by(valid_from=date(2030, 1, 1)).one()
    assert period.quality_fee_per_kwh == Decimal("0.0333")
    assert _bands_fee(period.transition_thresholds, 0) == Decimal("0.05")
    assert database_mismatches(db, modified) == []


def _bands_fee(thresholds, min_kwh):
    return next(t.monthly_fee_net_pln for t in thresholds if t.min_kwh_annual == min_kwh)


def test_load_fails_when_definition_in_db_extends_beyond_file_range(db):
    data_set = read_data_set([FIXTURE_DIR])
    load_data_set(db, data_set)
    db.flush()
    spec = build_definitions(data_set.operator_files[0])[0]
    spec.valid_from = date(2029, 12, 1)
    spec.valid_to = date(2030, 1, 31)
    db.add(_definition(spec))
    db.flush()
    before = _count_2030(db)
    outside_id = db.query(TariffDefinition).filter_by(osd_operator=PGE, valid_from=date(2029, 12, 1)).one().id

    with pytest.raises(TariffDataError) as caught:
        load_data_set(db, data_set)

    message = "\n".join(caught.value.errors)
    assert "poza zakres pliku" in message
    assert "2029-12-01 – 2030-01-31" in message
    assert _count_2030(db) == before  # nic nie usunięto
    assert db.get(TariffDefinition, outside_id) is not None


def test_load_fails_when_regulatory_period_in_db_extends_beyond_file_range(db):
    data_set = read_data_set([FIXTURE_DIR])
    load_data_set(db, data_set)
    db.add(
        RegulatoryPeriod(
            valid_from=date(2029, 12, 1),
            valid_to=date(2030, 1, 31),
            quality_fee_per_kwh=Decimal("0.03"),
            renewable_energy_fee_per_kwh=Decimal("0.004"),
            cogeneration_fee_per_kwh=Decimal("0.003"),
            excise_per_kwh=Decimal("0.005"),
            vat_rate=Decimal("0.23"),
            source="test",
        )
    )
    db.flush()
    before = _count_2030(db)

    with pytest.raises(TariffDataError) as caught:
        load_data_set(db, data_set)

    message = "\n".join(caught.value.errors)
    assert "poza zakres pliku" in message
    assert "2029-12-01 – 2030-01-31" in message
    assert _count_2030(db) == before


def test_load_unsupported_row_beyond_file_range_also_blocks_load(db):
    data_set = read_data_set([FIXTURE_DIR])
    spec = build_unsupported(data_set.operator_files[0])[0]
    spec.valid_from = date(2029, 6, 1)
    db.add(UnsupportedTariff(
        osd_operator=spec.operator, tariff_code=spec.code, name=spec.name, reason=spec.reason,
        valid_from=spec.valid_from, valid_to=spec.valid_to, source=spec.source,
    ))
    db.flush()

    with pytest.raises(TariffDataError) as caught:
        load_data_set(db, data_set)

    assert "poza zakres pliku" in "\n".join(caught.value.errors)
    assert db.query(UnsupportedTariff).filter_by(osd_operator=PGE, valid_from=date(2029, 6, 1)).count() == 1


# ---------------------------------------------------------------- baza = prawdziwe pliki


def test_real_data_loaded_into_db_matches_files_exactly(db):
    data_set = read_data_set([DATA_DIR])
    load_data_set(db, data_set)
    db.flush()

    mismatches = database_mismatches(db, data_set)
    assert mismatches == [], "\n".join(mismatches[:20])

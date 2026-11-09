"""ZP-81: zapisane scalanie plików urządzeń (superseded) i API zużycia oraz kosztu per urządzenie."""
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.models.EnergyDataFile import EnergyDataFile
from app.models.Simulation import Simulation
from app.models.User import User
from app.parsers import parse_energy_file
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.services.calculation_service import CalculationService
from test_energy_files import (
    T0,
    T1,
    T2,
    _all_devices_data,
    _create_devices_file,
    _create_user,
    _delete,
    _devices_document,
    _flat_tariff_repository,
    _get_data,
    _headers,
    _upload,
    client,
)


FIXTURES = Path(__file__).parent / "fixtures"
BACKEND_DIR = Path(__file__).resolve().parents[1]
METER_DEMO = FIXTURES / "meter_demo_30d.csv"
DEVICES_FROM_METER_DEMO = FIXTURES / "devices_from_meter_demo_30d.json"
DEVICES_DEMO = FIXTURES / "devices_demo_30d.json"
SAMPLE_DEVICES = BACKEND_DIR.parent / "frontend" / "public" / "samples" / "devices-example.json"
OCTOBER = ("2026-10-08T00:00:00", "2026-10-11T00:00:00")
# Progi czasu z ZP-81 dotyczą uruchomienia lokalnego; maszyny GitHub Actions (CI=true) są wolniejsze.
TIME_LIMIT_SCALE = 2.0 if os.getenv("CI") else 1.0
MIGRATION = BACKEND_DIR / "alembic" / "versions" / "b8d4f2a6c9e1_zapisane_scalanie_urzadzen.py"


@pytest.fixture
def db():
    """Jak w test_energy_files: _create_user zapisuje id użytkowników do usunięcia po teście."""
    session = SessionLocal()
    session.created_users = []
    yield session
    session.rollback()
    for user_id in session.created_users:
        session.query(User).filter(User.id == user_id).delete()
    session.commit()
    session.close()


def _usage(user, source, query=""):
    return client.get(f"/api/v1/energy-files/{source}/devices/usage{query}", headers=_headers(user))


def _october(document):
    """Pomocnik z ZP-79 zapisuje czas zimowy (+01:00); w październiku obowiązuje letni (+02:00)."""
    return json.loads(json.dumps(document).replace("+01:00", "+02:00"))


def _washer(*actions):
    return {"dev_wm": [(f"{day}T10:00:00", f"{day}T11:00:00", kwh) for day, kwh in actions]}


def _create_document_file(db, user, path, *, name, uploaded_at):
    return _create_devices_file(db, user, json.loads(path.read_text(encoding="utf-8")), name=name, uploaded_at=uploaded_at)


def _create_meter_file(db, user, path, *, name, uploaded_at):
    """Plik licznika z odczytami w energy_readings, jak po uploadzie."""
    with path.open("rb") as handle:
        parsed = parse_energy_file(handle)
    service = CalculationService(_flat_tariff_repository())
    results = service.calculate_with_report(parsed)
    energy_file = EnergyDataFile(
        user_id=user.id,
        file_name=name,
        uploaded_at=uploaded_at,
        data_start=datetime.date.fromisoformat(results["statistics"]["data_start"]),
        data_end=datetime.date.fromisoformat(results["statistics"]["data_end"]),
        records_count=results["statistics"]["records_count"],
        source_type=EnergyDataFile.SOURCE_METER,
        status=EnergyDataFile.STATUS_COMPLETED,
    )
    db.add(energy_file)
    db.flush()
    EnergyReadingRepository(db).replace_for_file(energy_file.id, service.quarter_hour_readings(parsed))
    db.add(Simulation(user_id=user.id, energy_data_file_id=energy_file.id, results=results))
    db.commit()
    return energy_file


def _washer_documents():
    """Przykład z ZP-81: pralka z plików A (8–10.10), B (9–10.10) i D (10.10), w kolejności uploadu."""
    a = _october(_devices_document(*OCTOBER, _washer(("2026-10-08", 0.8), ("2026-10-09", 1.2), ("2026-10-10", 1.0))))
    b = _october(_devices_document("2026-10-09T00:00:00", OCTOBER[1], _washer(("2026-10-10", 1.75))))
    d = _october(_devices_document("2026-10-10T00:00:00", OCTOBER[1], _washer(("2026-10-10", 1.95))))
    return [(a, "A.json", T0), (b, "B.json", T1), (d, "D.json", T2)]


def _washer_files(db, user, order=(0, 1, 2)):
    """Pliki A, B i D zapisane w podanej kolejności; data uploadu zawsze A < B < D."""
    documents = _washer_documents()
    files = {
        index: _create_devices_file(db, user, documents[index][0], name=documents[index][1], uploaded_at=documents[index][2])
        for index in order
    }
    return [files[index] for index in range(3)]


def _flags(db, files):
    return {
        (file_id, slot_start.date().isoformat()): superseded
        for file_id, slot_start, superseded in db.query(
            DeviceSlotUsage.energy_data_file_id, DeviceSlotUsage.slot_start, DeviceSlotUsage.superseded
        ).filter(DeviceSlotUsage.energy_data_file_id.in_([energy_file.id for energy_file in files]))
    }


def _flags_by_name(db, files):
    names = {energy_file.id: energy_file.file_name for energy_file in files}
    return {(names[file_id], day): superseded for (file_id, day), superseded in _flags(db, files).items()}


def _daily_washer_kwh(user):
    body = _usage(user, "all-devices", "?group_by=instance&resolution=1d").json()
    return body["groups"][0]["kwh"]


def test_washer_example_counts_only_the_newest_file_covering_each_day(db):
    user = _create_user(db)
    _washer_files(db, user)

    assert _daily_washer_kwh(user) == [0.8, 0.0, 1.95]
    results = _all_devices_data(user).json()["results"]
    assert results["tariffs"]["G11"]["total_usage_kwh"] == pytest.approx(2.75)
    assert results["statistics"]["records_count"] == 2


def test_superseded_flags_are_saved_per_file(db):
    user = _create_user(db)
    a, b, d = _washer_files(db, user)

    assert _flags(db, (a, b, d)) == {
        (a.id, "2026-10-08"): False, (a.id, "2026-10-09"): True, (a.id, "2026-10-10"): True,
        (b.id, "2026-10-10"): True,
        (d.id, "2026-10-10"): False,
    }


def test_file_saved_after_newer_uploads_is_covered_by_them(db):
    user = _create_user(db)
    # Najpierw D i B, na końcu A z najstarszą datą uploadu: zapis A widzi nowsze pliki.
    files = _washer_files(db, user, order=(2, 1, 0))

    assert _daily_washer_kwh(user) == [0.8, 0.0, 1.95]
    # Te same flagi co przy zapisie w kolejności uploadu.
    assert _flags_by_name(db, files) == _flags_by_name(db, _washer_files(db, _create_user(db)))


def test_upload_of_device_files_saves_period_and_flags(db):
    user = _create_user(db)
    service = CalculationService(_flat_tariff_repository())

    responses = [
        _upload(user, service, name, json.dumps(document).encode()) for document, name, _ in _washer_documents()
    ]
    files = [db.get(EnergyDataFile, uuid.UUID(response.json()["file_id"])) for response in responses]

    assert [response.status_code for response in responses] == [200, 200, 200]
    utc = datetime.timezone.utc
    assert (files[0].period_start, files[0].period_end) == (
        datetime.datetime(2026, 10, 7, 22, 0, tzinfo=utc), datetime.datetime(2026, 10, 10, 22, 0, tzinfo=utc),
    )
    assert _daily_washer_kwh(user) == [0.8, 0.0, 1.95]
    assert _flags(db, files)[(files[0].id, "2026-10-10")] is True


def test_migration_marks_the_same_flags_as_repository(db):
    user = _create_user(db)
    files = _washer_files(db, user)
    expected = _flags(db, files)
    db.query(DeviceSlotUsage).filter(
        DeviceSlotUsage.energy_data_file_id.in_([energy_file.id for energy_file in files])
    ).update({DeviceSlotUsage.superseded: False}, synchronize_session=False)
    spec = importlib.util.spec_from_file_location("migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    db.execute(text(migration.MARK_ALL_COVERED))

    assert _flags(db, files) == expected


def test_deleting_newer_files_restores_older_rows(db):
    user = _create_user(db)
    a, b, d = _washer_files(db, user)

    assert _delete(user, d.id).status_code == 204
    assert _daily_washer_kwh(user) == [0.8, 0.0, 1.75]
    assert _delete(user, b.id).status_code == 204
    assert _daily_washer_kwh(user) == [0.8, 1.2, 1.0]


def test_single_file_shows_its_own_rows_even_when_covered_by_newer_file(db):
    user = _create_user(db)
    a, _, _ = _washer_files(db, user)

    body = _usage(user, a.id, "?group_by=instance&resolution=1d").json()

    assert body["groups"][0]["kwh"] == [0.8, 1.2, 1.0]


def test_groups_sum_to_file_usage_and_dashboard_cost_without_pv(db):
    user = _create_user(db)
    energy_file = _create_document_file(db, user, DEVICES_FROM_METER_DEMO, name="dom.json", uploaded_at=T0)

    body = _usage(user, energy_file.id, "?group_by=category&resolution=15m").json()
    dashboard = _get_data(user, energy_file).json()["results"]["tariffs"]["G11"]
    usage = db.get(Simulation, _get_data(user, energy_file).json()["simulation_id"]).results["usage_15min"]

    per_quarter = [sum(group["kwh"][index] for group in body["groups"]) for index in range(len(body["periods"]))]
    expected = [
        kwh for day in sorted(usage) for kwh in usage[day] if kwh is not None
    ]
    assert len(body["periods"]) == 2884  # 30 dób, w tym 25.10 ze 100 kwadransami
    assert body["production"] is None
    assert sum(per_quarter) == pytest.approx(sum(expected), abs=0.01)
    assert body["total_kwh"] == pytest.approx(dashboard["total_usage_kwh"], abs=0.01)
    # Suma kosztów grup zaokrąglonych do groszy (7 kategorii) może odbiegać od kosztu Dashboardu o kilka groszy.
    assert body["total_cost_pln"] == pytest.approx(dashboard["estimated_cost_pln"], abs=0.05)
    assert body["tariff"] == {
        "name": "G11", "source": "default", "note": "Profil nie wskazuje taryfy, więc koszty są w taryfie G11.",
    }


def test_every_quarter_of_device_groups_matches_imported_series(db):
    user = _create_user(db)
    energy_file = _create_document_file(db, user, DEVICES_FROM_METER_DEMO, name="dom.json", uploaded_at=T0)

    body = _usage(user, energy_file.id, "?resolution=1d").json()
    data = _get_data(user, energy_file).json()["results"]["chart_daily"]

    assert [round(sum(group["kwh"][i] for group in body["groups"]), 2) for i in range(30)] == [
        pytest.approx(day["kwh"], abs=0.006) for day in data
    ]


def test_with_pv_consumption_minus_production_equals_import_minus_export(db):
    user = _create_user(db)
    energy_file = _create_document_file(db, user, SAMPLE_DEVICES, name="pv.json", uploaded_at=T0)
    with SAMPLE_DEVICES.open("rb") as handle:
        parsed = parse_energy_file(handle)
    readings = CalculationService.quarter_hour_readings(parsed)

    body = _usage(user, energy_file.id, "?resolution=15m").json()
    consumption = [sum(group["kwh"][i] for group in body["groups"]) for i in range(len(body["periods"]))]
    production = body["production"]["kwh"]
    by_time = {moment: used - exported for moment, used, exported in readings}
    periods = [datetime.datetime.fromisoformat(period).replace(tzinfo=None) for period in body["periods"]]

    assert body["production"]["total_kwh"] > 0
    assert [round(c - p, 4) for c, p in zip(consumption, production)] == [
        round(by_time.get(moment, 0.0), 4) for moment in periods
    ]


def test_group_metadata_filters_and_drill_down(db):
    user = _create_user(db)
    energy_file = _create_document_file(db, user, DEVICES_DEMO, name="dom.json", uploaded_at=T0)

    categories = _usage(user, energy_file.id).json()["groups"]
    types = _usage(user, energy_file.id, "?group_by=type&category=Pojazd%20elektryczny").json()["groups"]
    instances = _usage(user, energy_file.id, "?group_by=instance&type=ev_charger").json()

    assert {group["key"] for group in categories} == {"AGD", "Ogrzewanie", "Oświetlenie", "Pojazd elektryczny", "RTV/IT", "Inne"}
    assert [(group["key"], group["label"], group["category"]) for group in types] == [
        ("ev_charger", "Ładowarka EV", "Pojazd elektryczny")
    ]
    assert [(group["device_id"], group["device_name"], group["device_type"]) for group in instances["groups"]] == [
        ("dev_ev_01", "Ładowarka EV", "ev_charger")
    ]
    assert instances["production"] is None
    ev_category = next(group for group in categories if group["key"] == "Pojazd elektryczny")
    assert instances["groups"][0]["total_kwh"] == ev_category["total_kwh"]
    assert instances["total_cost_pln"] == ev_category["total_cost_pln"]


def test_flexible_filter_keeps_only_devices_that_can_be_moved(db):
    user = _create_user(db)
    energy_file = _create_document_file(db, user, DEVICES_DEMO, name="dom.json", uploaded_at=T0)

    everything = _usage(user, energy_file.id, "?group_by=instance").json()
    flexible = _usage(user, energy_file.id, "?group_by=instance&flexible=true").json()
    categories = {group["key"]: group for group in _usage(user, energy_file.id).json()["groups"]}

    modes = {group["device_id"]: group["flexibility_mode"] for group in everything["groups"]}
    assert modes["dev_wm_01"] == "shiftable" and modes["dev_ev_01"] == "interruptible" and modes["dev_fr_01"] == "fixed"
    assert {group["device_id"] for group in flexible["groups"]} == {
        device_id for device_id, mode in modes.items() if mode in ("shiftable", "interruptible")
    }
    assert flexible["production"] is None
    assert categories["AGD"]["flexible_devices_count"] == 3  # pralka, suszarka, zmywarka
    assert categories["Oświetlenie"]["flexible_devices_count"] == 0


def test_range_resolution_and_tariff_parameters(db):
    user = _create_user(db)
    energy_file = _create_document_file(db, user, DEVICES_DEMO, name="dom.json", uploaded_at=T0)

    hourly = _usage(user, energy_file.id, "?from=2026-10-25&to=2026-10-25&tariff=g11").json()

    assert hourly["tariff"]["source"] == "query"
    assert len(hourly["periods"]) == 25  # zmiana czasu: doba ma 25 godzin
    assert hourly["periods"][2] == "2026-10-25T02:00:00+02:00"
    assert hourly["periods"][3] == "2026-10-25T02:00:00+01:00"
    assert _usage(user, energy_file.id, "?tariff=G13").status_code == 422
    assert _usage(user, energy_file.id, "?from=2026-09-01").status_code == 422
    assert _usage(user, energy_file.id, "?resolution=5m").status_code == 422


def test_rest_of_house_for_matched_demo_pair_is_about_zero(db):
    user = _create_user(db)
    meter = _create_meter_file(db, user, METER_DEMO, name="licznik.csv", uploaded_at=T0)
    _create_document_file(db, user, DEVICES_FROM_METER_DEMO, name="dom.json", uploaded_at=T1)

    body = _usage(user, "all-devices", f"?meter={meter.id}&resolution=1d").json()
    rest = body["rest_of_house"]

    assert rest["meter_file_ids"] == [str(meter.id)]
    assert len(rest["common_days"]) == 30
    assert rest["exceeded_days"] == []
    assert rest["total_kwh"] == pytest.approx(0.0, abs=0.05)
    assert body["total_kwh"] == pytest.approx(sum(group["total_kwh"] for group in body["groups"]) + rest["total_kwh"])


def test_rest_of_house_is_meter_minus_devices_and_marks_exceeded_days(db):
    user = _create_user(db)
    meter = _create_meter_file(db, user, METER_DEMO, name="licznik.csv", uploaded_at=T0)
    document = _october(_devices_document("2026-10-05T00:00:00", "2026-10-07T00:00:00", {
        # Rozłożone na całą dobę, żeby w żadnym kwadransie nie przekroczyć licznika.
        "dev_small": [("2026-10-05T00:00:00", "2026-10-06T00:00:00", 0.4)],
        "dev_huge": [("2026-10-06T00:00:00", "2026-10-07T00:00:00", 90.0)],
    }))
    _create_devices_file(db, user, document, name="dom.json", uploaded_at=T1)

    rest = _usage(user, "all-devices", "?meter=all&resolution=1d").json()["rest_of_house"]
    meter_days = {day["date"]: day["kwh"] for day in _get_data(user, meter).json()["results"]["chart_daily"]}

    assert rest["common_days"] == ["2026-10-05", "2026-10-06"]
    # Wykres dzienny licznika jest zaokrąglony do 0,01 kWh.
    assert rest["kwh"][0] == pytest.approx(meter_days["2026-10-05"] - 0.4, abs=0.006)
    assert rest["exceeded_days"] == ["2026-10-06"]


@pytest.mark.parametrize("meter", ["all", "devices-file"])
def test_rest_of_house_requires_meter_file(db, meter):
    user = _create_user(db)
    devices = _create_document_file(db, user, DEVICES_DEMO, name="dom.json", uploaded_at=T0)

    response = _usage(user, "all-devices", f"?meter={devices.id if meter == 'devices-file' else 'all'}")

    assert response.status_code == 409


def test_meter_file_has_no_devices_and_others_files_are_not_found(db):
    user, other = _create_user(db), _create_user(db)
    meter = _create_meter_file(db, user, METER_DEMO, name="licznik.csv", uploaded_at=T0)
    devices = _create_document_file(db, other, DEVICES_DEMO, name="dom.json", uploaded_at=T0)

    assert _usage(user, meter.id).status_code == 409
    assert _usage(user, devices.id).status_code == 404
    assert _usage(user, "not-a-uuid").status_code == 404
    assert _usage(user, "all-devices").status_code == 409
    assert client.get(f"/api/v1/energy-files/{devices.id}/devices/usage").status_code == 401


def test_thirty_days_of_24_devices_respond_within_a_second(db):
    user = _create_user(db)
    energy_file = _create_document_file(db, user, DEVICES_DEMO, name="dom.json", uploaded_at=T0)

    started = time.perf_counter()
    response = _usage(user, energy_file.id, "?group_by=instance&resolution=15m")

    assert response.status_code == 200
    assert len(response.json()["groups"]) == 23  # 24 urządzenia, PV jest w production
    assert time.perf_counter() - started < 1.0 * TIME_LIMIT_SCALE


@pytest.fixture(scope="module")
def yearly_document(tmp_path_factory):
    path = tmp_path_factory.mktemp("rok") / "rok.json"
    subprocess.run(
        [sys.executable, str(BACKEND_DIR / "scripts" / "generate_devices_file.py"),
         "--start", "2025-01-01", "--days", "365", "--seed", "3", "--out", str(path)],
        check=True, capture_output=True,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_yearly_files_flags_and_aggregate_are_fast(db, yearly_document):
    user = _create_user(db)
    _create_devices_file(db, user, yearly_document, name="rok.json", uploaded_at=T0)
    parsed = parse_energy_file(BytesIO(json.dumps(yearly_document).encode()))
    newer = EnergyDataFile(
        user_id=user.id, file_name="rok_kopia.json", uploaded_at=T1, source_type=EnergyDataFile.SOURCE_DEVICES,
        status=EnergyDataFile.STATUS_COMPLETED, period_start=parsed.period_start, period_end=parsed.period_end,
    )
    db.add(newer)
    db.flush()

    repository = DeviceRepository(db)
    cover_older_files, flag_seconds = repository._cover_older_files, []

    def timed_cover(*args):
        started = time.perf_counter()
        cover_older_files(*args)
        flag_seconds.append(time.perf_counter() - started)

    repository._cover_older_files = timed_cover
    repository.save_for_file(user_id=user.id, energy_data_file_id=newer.id, devices=parsed.devices)
    db.commit()
    results = CalculationService(_flat_tariff_repository()).calculate_with_report(parsed)
    newer.data_start = datetime.date.fromisoformat(results["statistics"]["data_start"])
    newer.data_end = datetime.date.fromisoformat(results["statistics"]["data_end"])
    db.add(Simulation(user_id=user.id, energy_data_file_id=newer.id, results=results))
    db.commit()

    _all_devices_data(user)  # rozgrzewka połączenia i cache zapytań
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        response = _all_devices_data(user)
        timings.append(time.perf_counter() - started)
    # Najlepszy z trzech pomiarów: pojedynczy bywa wolniejszy przez obciążenie bazy innymi testami.
    aggregate_seconds = min(timings)

    assert response.status_code == 200
    assert response.json()["results"]["statistics"]["records_count"] == len(yearly_document["energy_usage"])
    covered = db.query(DeviceSlotUsage).filter(DeviceSlotUsage.superseded.is_(True)).join(
        EnergyDataFile, EnergyDataFile.id == DeviceSlotUsage.energy_data_file_id
    ).filter(EnergyDataFile.user_id == user.id).count()
    assert covered == sum(len(action_slots) for action_slots in _slots(parsed))
    assert len(flag_seconds) == 1 and flag_seconds[0] < 3.0 * TIME_LIMIT_SCALE
    assert aggregate_seconds < 0.5 * TIME_LIMIT_SCALE


def _slots(parsed):
    return [action.slots_kwh for device in parsed.devices for action in device.actions]

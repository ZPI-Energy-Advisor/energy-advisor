import datetime
import json
import time
from io import BytesIO

import pytest

from app.models.EnergyDataFile import EnergyDataFile
from app.models.EnergyReading import EnergyReading
from app.models.Simulation import Simulation
from app.models.UserProfile import UserProfile
from app.parsers import parse_energy_file
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.services.calculation_service import CalculationService
from app.database import SessionLocal
from app.models.User import User
from timing import TIME_LIMIT_SCALE
from test_device_usage import SAMPLE_DEVICES
from test_energy_files import (
    T0, T1, _create_devices_file, _create_series_file, _create_user, _days, _headers,
    _series_results, client,
)

pytestmark = pytest.mark.usefixtures("flat_tariffs")
EXPORT_HOURS = range(10, 14)


@pytest.fixture
def db():
    session = SessionLocal()
    session.created_users = []
    yield session
    session.rollback()
    for user_id in session.created_users:
        session.query(User).filter(User.id == user_id).delete()
    session.commit()
    session.close()


def _save_profile(db, user, pv=None):
    db.add(UserProfile(
        user_id=user.id,
        base_info={
            "type_of_property": "apartment", "year_of_construction": 2000, "heating_area_m2": 60,
            "number_of_residents": 2, "town": "Wrocław", "postal_code": "50-370", "distribution_operator": "PGE",
            "phase_type": "1_phase", "contracted_power_kw": 5, "billing_cycle": 2,
            "billing_period_start_date": "2024-05-01",
        },
        consumption_and_tariff={"tariff_type": "G11", "dynamic_price": False},
        pv_config=pv or {"mode": "none"},
    ))
    db.commit()


def _meter_file(db, user, start, days, kwh, *, name="licznik.csv", uploaded_at=T0, export=0.0):
    """Plik z licznika z serią zużycia i odczytami w bazie; w godzinach EXPORT_HOURS tylko oddanie `export`."""
    first = datetime.date.fromisoformat(start)
    usage, readings = {}, []
    for offset in range(days):
        day = first + datetime.timedelta(days=offset)
        slots = []
        for slot in range(96):
            moment = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(minutes=15 * slot)
            exported = export if export and moment.hour in EXPORT_HOURS else 0.0
            used = 0.0 if exported else kwh
            slots.append(used)
            readings.append((moment, used, exported))
        usage[day.isoformat()] = slots
    energy_file = EnergyDataFile(
        user_id=user.id, file_name=name, uploaded_at=uploaded_at, data_start=first,
        data_end=first + datetime.timedelta(days=days - 1), records_count=days * 96,
        source_type=EnergyDataFile.SOURCE_METER, status=EnergyDataFile.STATUS_COMPLETED,
    )
    db.add(energy_file)
    db.commit()
    db.add(Simulation(user_id=user.id, energy_data_file_id=energy_file.id, results=_series_results(usage)))
    db.add_all(
        EnergyReading(energy_data_file_id=energy_file.id, measured_at=moment, energy_kwh=used, exported_kwh=exported)
        for moment, used, exported in readings
    )
    db.commit()
    return energy_file


def _comparison(user, source_id, query=""):
    return client.get(f"/api/v1/energy-files/{source_id}/tariff-comparison{query}", headers=_headers(user))


def _payable(body, key="G11"):
    return next(entry["payable_gross"] for entry in body["tariffs"] if entry["key"] == key)


@pytest.mark.parametrize(
    "pv", [None, {"mode": "net_metering", "power_of_pv_kwp": 5}], ids=["bez-pv", "net-metering"],
)
def test_comparison_of_whole_file_equals_calculation_results_and_dashboard(db, pv):
    user = _create_user(db)
    _save_profile(db, user, pv)
    energy_file = _meter_file(db, user, "2024-06-01", 30, 0.25, export=0.5)

    calculation = client.get(f"/api/v1/upload/calculation-details/{energy_file.id}", headers=_headers(user)).json()
    compared = _comparison(user, energy_file.id).json()
    profile_only = _comparison(user, energy_file.id, "?tariffs=profile").json()
    dashboard = client.get(
        f"/api/v1/energy-files/{energy_file.id}/data?tariffs=profile", headers=_headers(user)
    ).json()["results"]

    payable = calculation["tariff_calculation"]["payable_gross"]
    assert _payable(compared) == _payable(profile_only) == payable
    assert dashboard["tariffs"]["G11"]["estimated_cost_pln"] == payable
    assert dashboard["pricing"]["tariff_key"] == compared["selected_tariff"] == "G11"
    assert compared["from_profile"] is True and compared["tariffs"][0]["is_profile"] is True
    assert compared["pv_mode"] == (pv or {}).get("mode")
    if pv is None:
        assert payable == 30 * 20 * 4 * 0.25
        assert any("energii oddanej do sieci" in warning for warning in compared["warnings"])
    else:
        assert payable < 30 * 20 * 4 * 0.25


def test_comparison_of_date_range_bills_only_its_days(db):
    user = _create_user(db)
    energy_file = _meter_file(db, user, "2024-06-01", 10, 0.25)

    body = _comparison(user, energy_file.id, "?from=2024-06-03&to=2024-06-04").json()

    assert (body["date_from"], body["date_to"]) == ("2024-06-03", "2024-06-04")
    assert _payable(body) == 2 * 96 * 0.25
    assert body["annual_consumption"]["days"] == 2
    assert body["from_profile"] is False and body["operator"] == "PGE"
    assert body["cheapest_tariff"] == "G11" and body["tariffs"][0]["difference_to_profile"] == 0


def test_all_files_comparison_takes_newest_file_where_files_overlap(db):
    user = _create_user(db)
    _meter_file(db, user, "2024-06-01", 10, 0.25, name="a.csv", uploaded_at=T0)
    _meter_file(db, user, "2024-06-06", 10, 0.5, name="b.csv", uploaded_at=T1)

    body = _comparison(user, "all").json()
    june = _comparison(user, "all", "?from=2024-06-01&to=2024-06-05").json()

    assert body["source_name"] == "Wszystkie pliki" and body["source_type"] == "meter"
    assert _payable(body) == 5 * 24 + 10 * 48
    assert _payable(june) == 5 * 24


def test_all_files_comparison_with_pv_equals_single_file(db):
    user = _create_user(db)
    _save_profile(db, user, {"mode": "net_metering", "power_of_pv_kwp": 5})
    energy_file = _meter_file(db, user, "2024-06-01", 20, 0.25, export=0.5)

    assert _payable(_comparison(user, "all").json()) == _payable(_comparison(user, energy_file.id).json())


def test_device_files_comparison_bills_usage_series(db):
    user = _create_user(db)
    usage = _days("2024-06-01", 3, 0.25)
    energy_file = _create_series_file(db, user, usage, name="dom.json", uploaded_at=T0, actions_per_day={"2024-06-01": 1})

    single = _comparison(user, energy_file.id).json()
    every = _comparison(user, "all-devices").json()
    every_data = client.get("/api/v1/energy-files/all-devices/data", headers=_headers(user)).json()["results"]

    assert _payable(single) == 3 * 24
    assert _payable(every) == every_data["tariffs"]["G11"]["estimated_cost_pln"]
    assert single["source_type"] == every["source_type"] == "devices"


def test_comparison_of_other_users_file_is_not_found(db):
    owner, other = _create_user(db), _create_user(db)
    energy_file = _meter_file(db, owner, "2024-06-01", 2, 0.25)

    assert _comparison(other, energy_file.id).status_code == 404
    assert _comparison(other, "1d2c3b4a-0000-0000-0000-000000000000").status_code == 404
    assert _comparison(other, "nie-plik").status_code == 404
    assert _comparison(other, "all").status_code == 409
    assert _comparison(owner, energy_file.id).status_code == 200


def test_range_outside_file_is_rejected(db):
    user = _create_user(db)
    energy_file = _meter_file(db, user, "2024-06-01", 2, 0.25)

    response = _comparison(user, energy_file.id, "?from=2024-05-01&to=2024-06-02")

    assert response.status_code == 422


@pytest.mark.perf
def test_year_of_readings_is_compared_quickly(db):
    user = _create_user(db)
    energy_file = _meter_file(db, user, "2024-01-01", 366, 0.25, export=0.3)
    _save_profile(db, user, {"mode": "net_metering", "power_of_pv_kwp": 5})

    best = float("inf")
    for _ in range(2):
        started = time.perf_counter()
        response = _comparison(user, energy_file.id)
        best = min(best, time.perf_counter() - started)

    assert response.status_code == 200
    assert best < 1.5 * TIME_LIMIT_SCALE


def test_all_device_files_have_the_same_export_as_readings_of_the_file(db):
    user = _create_user(db)
    _save_profile(db, user, {"mode": "net_metering", "power_of_pv_kwp": 5})
    document = json.loads(SAMPLE_DEVICES.read_text(encoding="utf-8"))
    energy_file = _create_devices_file(db, user, document, name="pv.json", uploaded_at=T0)
    parsed = parse_energy_file(BytesIO(json.dumps(document).encode()))
    readings = CalculationService().quarter_hour_readings(parsed)
    EnergyReadingRepository(db).replace_for_file(energy_file.id, readings)
    db.commit()

    single = _comparison(user, energy_file.id).json()
    every = _comparison(user, "all-devices").json()
    exported = sum(exported for _, _, exported in readings)

    assert exported > 0
    assert _payable(every) == _payable(single)
    assert _payable(single) < sum(used for _, used, _ in readings)

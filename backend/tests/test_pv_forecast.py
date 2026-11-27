import datetime as dt
from collections import defaultdict
from decimal import Decimal

import pytest

from app.api.v1.deps import get_pv_forecast_service
from app.models.UserProfile import UserProfile as UserProfileRow
from app.models.WeatherObservation import WeatherObservation
from app.parsers import parse_energy_file
from app.providers.weather import Plane, WeatherPoint, WeatherProviderError
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.weather_repository import WeatherRepository
from app.schemas.user_profile import UserProfile
from app.services.pv_forecast import (
    DEFAULT_COEFFICIENT,
    NoPvInstallationError,
    clear_calibrations,
    PvArray,
    PvForecastService,
    PvForecastUnavailableError,
    ac_kwh,
    calibrate,
    dc_kw,
)
from app.services.weather_service import Cell, WeatherService
from main import app
from pv_demo import DEVICES_DEMO, demo_days, demo_production, demo_weather_hours, local_day
from test_users_api import profile_payload

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
CELL = Cell(Decimal("51.1"), Decimal("17.0"))
SOUTH = Plane(35, 0)
ARRAYS = [PvArray(6.0, SOUTH)]
DEMO_DAY = dt.date(2026, 10, 13)


@pytest.fixture(autouse=True)
def _fresh_calibrations():
    clear_calibrations()
    yield
    clear_calibrations()


def test_model_is_zero_at_night_and_limited_by_inverter():
    assert dc_kw(ARRAYS, [SOUTH], [0.0], 10.0) == 0.0
    assert dc_kw(ARRAYS, [SOUTH], [None], 10.0) is None
    assert ac_kwh(dc_kw(ARRAYS, [SOUTH], [1100.0], 5.0), 0.9, 4.0) == pytest.approx(1.0)


def test_hot_panels_produce_less_than_cold_ones():
    cold = dc_kw(ARRAYS, [SOUTH], [800.0], 0.0)
    hot = dc_kw(ARRAYS, [SOUTH], [800.0], 35.0)

    assert cold > 4.8 > hot


def test_groups_of_panels_add_up_with_their_own_irradiance():
    east = Plane(35, -90)
    arrays = [PvArray(4.0, SOUTH), PvArray(2.0, east)]

    assert dc_kw(arrays, [east, SOUTH], [100.0, 500.0], None) == pytest.approx(4 * 0.5 + 2 * 0.1)


def test_calibration_on_demo_house_meets_acceptance_criteria():
    days = demo_days(CELL)
    production = demo_production()
    calibration = calibrate(ARRAYS, [SOUTH], production, days, 6.0)
    actual = defaultdict(float)
    for moment, kwh in production.items():
        actual[local_day(moment)] += kwh

    errors = {}
    for day, weather in days.items():
        predicted = sum(ac_kwh(dc_kw(ARRAYS, [SOUTH], q.tilted_w_m2, q.temperature_c), calibration.coefficient, 6.0)
                        for q in weather.quarters)
        errors[day] = abs(predicted - actual[day]) / actual[day]

    assert calibration.source == "history" and calibration.days == 30
    assert 0.8 < calibration.coefficient < 0.92
    assert calibration.mape < 0.1
    assert max(errors.values()) < 0.25


def test_estimated_panels_take_their_size_from_the_file_production():
    days = demo_days(CELL)
    production = demo_production()
    typical = [PvArray(3.0, SOUTH)]

    entered = calibrate(typical, [SOUTH], production, days, 6.0)
    estimated = calibrate(typical, [SOUTH], production, days, 6.0, estimated=True)
    real = calibrate(ARRAYS, [SOUTH], production, days, 6.0)

    # Panele z profilu: współczynnik najwyżej 1,1 i uwaga, że plik do nich nie pasuje.
    assert entered.coefficient == 1.1 and "nie pasuje" in entered.note
    # Panele szacunkowe: moc dopasowana do pliku, bez uwagi, a prognoza jak dla prawdziwych 6 kWp.
    assert estimated.note is None
    assert estimated.coefficient == pytest.approx(2 * real.coefficient, rel=0.01)
    assert estimated.effective_kwp == pytest.approx(6.0 * real.coefficient / 0.8, abs=0.1)
    assert real.effective_kwp is None


def test_calibration_ignores_snow_day_and_clipped_quarters():
    days = demo_days(CELL)
    production = demo_production()
    snowy = {moment: kwh * 0.05 if local_day(moment) == DEMO_DAY else kwh for moment, kwh in production.items()}

    clean = calibrate(ARRAYS, [SOUTH], production, days, 6.0)
    with_snow = calibrate(ARRAYS, [SOUTH], snowy, days, 6.0)
    small_inverter = calibrate(ARRAYS, [SOUTH], {m: min(kwh, 0.5) for m, kwh in production.items()}, days, 2.0)

    assert with_snow.days == 29 and abs(with_snow.coefficient - clean.coefficient) < 0.01
    # Dzień ze śniegiem jest wśród dni z danymi, ale nie w dopasowaniu.
    assert (with_snow.candidate_days, with_snow.days) == (30, 29)
    assert abs(small_inverter.coefficient - clean.coefficient) < 0.05


@pytest.mark.parametrize(
    "production, days, note",
    [
        ({}, None, "Brak pliku urządzeń"),
        (None, {}, "Brak pogody"),
        (None, "two", "Za mało dni"),
    ],
)
def test_calibration_falls_back_to_default(production, days, note):
    all_days = demo_days(CELL)
    production = demo_production() if production is None else production
    if days is None:
        days = all_days
    elif days == "two":
        days = dict(list(all_days.items())[:2])

    calibration = calibrate(ARRAYS, [SOUTH], production, days, 6.0)

    assert (calibration.coefficient, calibration.source) == (DEFAULT_COEFFICIENT, "default")
    assert note in calibration.note


def test_production_that_does_not_fit_panels_is_clamped_with_note():
    calibration = calibrate([PvArray(1.0, SOUTH)], [SOUTH], demo_production(), demo_days(CELL), 6.0)

    assert calibration.coefficient == 1.1
    assert "nie pasuje do paneli" in calibration.note


PV = {"mode": "net_billing", "type_of_price": "RCE", "installation": {"arrays": [{"power_kwp": 6.0, "azimuth": 0, "tilt": 35}]}}


def _profile(pv=PV, approximate=False):
    payload = profile_payload()
    payload["base_info"]["location"] = {
        "latitude": 51.11, "longitude": 17.03, "source": "postal_region" if approximate else "postal_code",
    }
    payload["pv_config"] = pv
    return payload


@pytest.fixture
def demo_house(db, user_a):
    def clean():
        db.query(WeatherObservation).filter(
            WeatherObservation.latitude == CELL.latitude, WeatherObservation.longitude == CELL.longitude
        ).delete(synchronize_session=False)
        db.commit()

    clean()
    start, temperatures, tilted = demo_weather_hours()
    points = [
        WeatherPoint(start + dt.timedelta(hours=hour), 60, temperatures[hour], 0, tilted[hour], {"35/0": tilted[hour]})
        for hour in range(len(temperatures)) if tilted[hour] is not None
    ]
    WeatherRepository(db).upsert(CELL.latitude, CELL.longitude, "archive", points, NOW)
    energy_file = EnergyDataFileRepository(db).create(user_id=user_a.id, file_name="dom.json")
    with DEVICES_DEMO.open("rb") as handle:
        DeviceRepository(db).save_for_file(
            user_id=user_a.id, energy_data_file_id=energy_file.id, devices=parse_energy_file(handle).devices
        )
    db.add(UserProfileRow(user_id=user_a.id, **_profile()))
    db.commit()
    yield user_a
    clean()


class OfflineClient:
    def forecast(self, *args):
        raise WeatherProviderError("brak sieci", retryable=False)

    archive = forecast


def service(db, now=NOW):
    return PvForecastService(WeatherService(WeatherRepository(db), client=OfflineClient(), now=lambda: now), DeviceRepository(db))


def test_forecast_for_demo_day_matches_production_from_file(db, demo_house):
    forecast = service(db).forecast(demo_house.id, UserProfile.model_validate(_profile()), DEMO_DAY)
    actual = sum(kwh for moment, kwh in demo_production().items() if local_day(moment) == DEMO_DAY)

    assert len(forecast.quarters) == 96 and forecast.basis == "weather"
    assert forecast.calibration.source == "history" and forecast.inverter_kw == 6.0
    assert abs(forecast.total_kwh - actual) / actual < 0.25
    assert all(q.kwh == 0 for q in forecast.quarters if q.start.astimezone(UTC).hour in (0, 1, 2, 3, 20, 21, 22))


def test_forecast_on_dst_day_has_100_quarters(db, demo_house):
    forecast = service(db).forecast(demo_house.id, UserProfile.model_validate(_profile()), dt.date(2026, 10, 25))

    assert len(forecast.quarters) == 100


def test_missing_weather_uses_recent_days_and_says_so(db, demo_house):
    forecast = service(db).forecast(demo_house.id, UserProfile.model_validate(_profile()), dt.date(2026, 10, 31))

    assert forecast.basis == "recent_days" and forecast.total_kwh > 1
    assert any("średnią z ostatnich dni" in note for note in forecast.notes)
    assert forecast.weather_fetched_at is None


def test_partial_weather_is_filled_from_recent_days(db, demo_house):
    db.query(WeatherObservation).filter(
        WeatherObservation.latitude == CELL.latitude,
        WeatherObservation.interval_start >= dt.datetime(2026, 10, 30, 10, tzinfo=UTC),
        WeatherObservation.interval_start < dt.datetime(2026, 10, 30, 12, tzinfo=UTC),
    ).delete(synchronize_session=False)
    db.commit()

    forecast = service(db).forecast(demo_house.id, UserProfile.model_validate(_profile()), dt.date(2026, 10, 30))

    assert forecast.basis == "mixed" and forecast.complete
    assert {q.basis for q in forecast.quarters if 10 <= q.start.astimezone(UTC).hour < 12} == {"recent_days"}


def test_no_weather_at_all_is_unavailable(db, demo_house):
    with pytest.raises(PvForecastUnavailableError):
        service(db).forecast(demo_house.id, UserProfile.model_validate(_profile()), dt.date(2026, 6, 1))


def test_profile_without_pv_has_no_forecast(db, demo_house):
    with pytest.raises(NoPvInstallationError):
        service(db).forecast(demo_house.id, UserProfile.model_validate(_profile(pv={"mode": "none"})), DEMO_DAY)


def test_estimated_installation_and_approximate_location_are_flagged(db, demo_house):
    estimated = {"mode": "net_billing", "type_of_price": "RCE"}

    forecast = service(db).forecast(demo_house.id, UserProfile.model_validate(_profile(estimated, True)), DEMO_DAY)

    assert forecast.estimated_installation and forecast.approximate_location
    assert len(forecast.notes) == 2


def test_calibration_is_reused_until_files_panels_or_hour_change(db, demo_house, monkeypatch):
    calls = []
    original = PvForecastService._calibrate

    def counted(self, *args):
        calls.append(args)
        return original(self, *args)

    monkeypatch.setattr(PvForecastService, "_calibrate", counted)
    profile = UserProfile.model_validate(_profile())
    service(db).forecast(demo_house.id, profile, DEMO_DAY)
    service(db).forecast(demo_house.id, profile, DEMO_DAY + dt.timedelta(days=1))
    assert len(calls) == 1

    another = EnergyDataFileRepository(db).create(user_id=demo_house.id, file_name="drugi.json")
    another.status = "completed"
    db.commit()
    service(db).forecast(demo_house.id, profile, DEMO_DAY)
    service(db, NOW + dt.timedelta(hours=1)).forecast(demo_house.id, profile, DEMO_DAY)
    two_groups = {"mode": "net_billing", "type_of_price": "RCE", "installation": {"arrays": [
        {"power_kwp": 3.0, "azimuth": 0, "tilt": 35}, {"power_kwp": 3.0, "azimuth": 0, "tilt": 35}]}}
    service(db).forecast(demo_house.id, UserProfile.model_validate(_profile(two_groups)), DEMO_DAY)

    assert len(calls) == 4


def test_house_without_device_file_uses_default_coefficient(db, user_b, demo_house):
    forecast = service(db).forecast(user_b.id, UserProfile.model_validate(_profile()), DEMO_DAY)

    assert (forecast.calibration.source, forecast.calibration.coefficient) == ("default", DEFAULT_COEFFICIENT)
    assert forecast.inverter_kw is None


@pytest.fixture
def pv_api(db):
    app.dependency_overrides[get_pv_forecast_service] = lambda: service(db)
    yield
    app.dependency_overrides.pop(get_pv_forecast_service, None)


def test_pv_forecast_endpoint(db, demo_house, client_a, pv_api):
    response = client_a.get("/api/v1/pv/forecast", params={"date": DEMO_DAY.isoformat()})

    body = response.json()
    assert response.status_code == 200
    assert body["calibration"]["source"] == "history" and body["basis"] == "weather"
    assert len(body["intervals"]) == 96 and body["total_kwh"] > 15
    assert body["intervals"][0] == {"start": "2026-10-12T22:00:00Z", "kwh": 0.0, "basis": "weather"}


def test_pv_forecast_endpoint_errors(db, demo_house, client_a, client_b, anonymous_client, pv_api):
    assert client_a.get("/api/v1/pv/forecast", params={"date": "2026-11-26"}).status_code == 422
    assert client_a.get("/api/v1/pv/forecast", params={"date": "2026-06-01"}).status_code == 503
    assert client_b.get("/api/v1/pv/forecast").status_code == 404
    assert anonymous_client.get("/api/v1/pv/forecast").status_code == 401
    row = db.get(UserProfileRow, demo_house.id)
    row.pv_config = {"mode": "none"}
    db.commit()
    assert client_a.get("/api/v1/pv/forecast", params={"date": DEMO_DAY.isoformat()}).status_code == 404


def test_partial_weather_without_recent_days_is_incomplete(db, demo_house):
    db.query(WeatherObservation).filter(
        WeatherObservation.latitude == CELL.latitude,
        WeatherObservation.interval_start < dt.datetime(2026, 10, 1, 10, tzinfo=UTC),
    ).delete(synchronize_session=False)
    db.commit()

    forecast = service(db).forecast(demo_house.id, UserProfile.model_validate(_profile()), dt.date(2026, 10, 1))

    assert not forecast.complete and forecast.total_kwh > 5
    assert any("nie liczymy" in note for note in forecast.notes)

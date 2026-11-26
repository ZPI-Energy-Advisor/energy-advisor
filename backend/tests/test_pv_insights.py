import datetime as dt
from collections import defaultdict
from decimal import Decimal

import pytest

from app.api.v1.deps import get_pv_insights_service
from app.models.EnergyDataFile import EnergyDataFile
from app.models.RcePriceObservation import RcePriceObservation
from app.models.UserProfile import UserProfile as UserProfileRow
from app.models.WeatherObservation import WeatherObservation
from app.parsers import parse_energy_file
from app.providers.prices.base import PricePoint, local_day_bounds_utc
from app.providers.prices.pse_provider import PseRcePriceProvider
from app.providers.weather import WeatherPoint, WeatherProviderError
from app.repositories.device_repository import DeviceRepository
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.repositories.user_repository import UserRepository
from app.repositories.weather_repository import WeatherRepository
from app.schemas.user_profile import UserProfile
from app.services.calculation_service import CalculationService
from app.services.pv_forecast import PvForecastService, clear_calibrations
from app.services.pv_insights import (
    PvInsightsService,
    _naive_local,
    clear_typical_profiles,
    device_day,
    hourly_balance,
    meter_day,
)
from app.services.pv_service import DynamicMarketPriceResolver
from app.services.schedule_prices import SchedulePriceService
from app.services.weather_service import Cell, WeatherService
from main import app
from pv_demo import DEVICES_DEMO, demo_production, demo_weather_hours, local_day
from tariff_helpers import FlatTariffRepository
from test_users_api import profile_payload

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
CELL = Cell(Decimal("51.1"), Decimal("17.0"))
DEMO_DAY = dt.date(2026, 10, 13)
PV = {"mode": "net_billing", "type_of_price": "RCE", "installation": {"arrays": [{"power_kwp": 6.0, "azimuth": 0, "tilt": 35}]}}
RCE_PLN_MWH = Decimal("500")


@pytest.fixture(autouse=True)
def _fresh_calibrations():
    clear_calibrations()
    clear_typical_profiles()
    yield
    clear_calibrations()
    clear_typical_profiles()


def at(hour, minute=0, day=DEMO_DAY):
    return dt.datetime.combine(day, dt.time(hour, minute), UTC)


def test_hourly_balance_nets_production_and_consumption_within_the_hour():
    production = {at(10, 0): 0.5, at(10, 15): 0.5, at(10, 30): 0.5, at(10, 45): 0.5, at(11, 0): 0.2}
    consumption = {at(10, 0): 1.0, at(10, 45): 0.2, at(11, 0): 0.5}

    hours = hourly_balance(production, consumption)

    assert hours == [(at(10), pytest.approx(1.2), pytest.approx(0.8), pytest.approx(0.0)),
                     (at(11), pytest.approx(0.2), pytest.approx(0.0), pytest.approx(0.3))]


def test_device_day_without_inverter_slots_is_zero_production_when_inverter_is_in_the_file():
    quarters = [at(10), at(10, 15)]
    slots = {at(10): (0.3, 0.0)}

    covered = device_day(quarters, slots, inverter_in_file=True)
    without_inverter = device_day(quarters, slots, inverter_in_file=False)

    assert covered.actual == {at(10): 0.0, at(10, 15): 0.0}
    assert covered.consumption == {at(10): 0.3, at(10, 15): 0.0}
    assert without_inverter.actual is None


def test_meter_file_without_any_export_is_treated_as_house_before_panels():
    quarters = [at(10), at(10, 15)]
    naive = [_naive_local(q) for q in quarters]
    readings = {naive[0]: (0.4, 0.0, "old"), naive[1]: (0.1, 0.2, "new")}
    model = {at(10): 0.5, at(10, 15): 0.5}

    before_panels = meter_day(quarters, {naive[0]: readings[naive[0]]}, model, files_with_export={"new"})
    with_panels = meter_day(quarters, readings, model, files_with_export={"new"})

    assert before_panels.source == "meter_without_pv"
    assert before_panels.consumption == {at(10): 0.4, at(10, 15): 0.0}
    assert with_panels.source == "meter"
    assert with_panels.consumption == {at(10): pytest.approx(0.9), at(10, 15): pytest.approx(0.4)}


def _profile(pv=PV, tariff="G11"):
    payload = profile_payload(tariff)
    payload["base_info"]["location"] = {"latitude": 51.11, "longitude": 17.03, "source": "postal_code"}
    payload["pv_config"] = pv
    return payload


@pytest.fixture
def house(db, user_a):
    def clean():
        db.query(WeatherObservation).filter(
            WeatherObservation.latitude == CELL.latitude, WeatherObservation.longitude == CELL.longitude
        ).delete(synchronize_session=False)
        db.query(RcePriceObservation).filter(
            RcePriceObservation.source == PseRcePriceProvider.source,
            RcePriceObservation.business_date.between(dt.date(2026, 9, 1), dt.date(2026, 12, 31)),
        ).delete(synchronize_session=False)
        db.commit()

    clean()
    start, temperatures, tilted = demo_weather_hours()
    WeatherRepository(db).upsert(CELL.latitude, CELL.longitude, "archive", [
        WeatherPoint(start + dt.timedelta(hours=hour), 60, temperatures[hour], 40, tilted[hour], {"35/0": tilted[hour]})
        for hour in range(len(temperatures)) if tilted[hour] is not None
    ], NOW)
    files = EnergyDataFileRepository(db)
    energy_file = files.create(user_id=user_a.id, file_name="dom.json")
    with DEVICES_DEMO.open("rb") as handle:
        parsed = parse_energy_file(handle)
    DeviceRepository(db).save_for_file(user_id=user_a.id, energy_data_file_id=energy_file.id, devices=parsed.devices)
    EnergyReadingRepository(db).replace_for_file(energy_file.id, CalculationService.quarter_hour_readings(parsed))
    energy_file.status = EnergyDataFile.STATUS_COMPLETED
    energy_file.source_type = EnergyDataFile.SOURCE_DEVICES
    energy_file.data_start, energy_file.data_end = dt.date(2026, 10, 1), dt.date(2026, 10, 30)
    files.save(energy_file)
    db.add(UserProfileRow(user_id=user_a.id, **_profile()))
    db.commit()
    yield user_a
    clean()


def add_weather(db, day, source="forecast"):
    start, end = local_day_bounds_utc(day)
    WeatherRepository(db).upsert(CELL.latitude, CELL.longitude, source, [
        WeatherPoint(start + dt.timedelta(minutes=15 * q), 15, 5.0, 20, 300.0 if 32 <= q < 64 else 0.0,
                     {"35/0": 300.0 if 32 <= q < 64 else 0.0})
        for q in range(int((end - start) / dt.timedelta(minutes=15)))
    ], NOW)


def add_rce(db, day):
    start, end = local_day_bounds_utc(day)
    moment, points = start, []
    while moment < end:
        points.append(PricePoint(PseRcePriceProvider.source, moment, 15, day, RCE_PLN_MWH))
        moment += dt.timedelta(minutes=15)
    DynamicPriceRepository(db).upsert_many(points)


class OfflineClient:
    def forecast(self, *args):
        raise WeatherProviderError("brak sieci", retryable=False)

    archive = forecast


def service(db, now=NOW, client=None):
    weather = WeatherService(WeatherRepository(db), client=client or OfflineClient(), now=lambda: now)
    resolver = DynamicMarketPriceResolver(DynamicPriceRepository(db))
    prices = SchedulePriceService(UserRepository(db), FlatTariffRepository(), resolver)
    return PvInsightsService(
        PvForecastService(weather, DeviceRepository(db)),
        EnergyReadingRepository(db), EnergyDataFileRepository(db), prices, resolver,
    )


def detail(db, user, day, profile=None, now=NOW):
    insights = service(db, now)
    profile = UserProfile.model_validate(profile or _profile())
    return insights.day(user.id, profile, insights.setup(user.id, profile), day)


def test_past_day_shows_file_production_model_and_value(db, house):
    add_rce(db, DEMO_DAY)

    day = detail(db, house, DEMO_DAY)

    actual = sum(kwh for moment, kwh in demo_production().items() if local_day(moment) == DEMO_DAY)
    balance = day.balance
    assert (day.kind, day.consumption_source, len(day.intervals)) == ("past", "devices", 96)
    assert day.actual_kwh == pytest.approx(actual, abs=0.01)
    assert abs(day.model_kwh - actual) / actual < 0.25
    assert balance.production_kwh == pytest.approx(actual, abs=0.01)
    assert balance.self_kwh + balance.export_kwh == pytest.approx(balance.production_kwh, abs=0.02)
    assert balance.self_kwh + balance.import_kwh == pytest.approx(balance.consumption_kwh, abs=0.02)
    assert balance.value.purchase_price == pytest.approx(1.0)
    assert balance.value.export_price == pytest.approx(0.5 * 1.23)
    assert not balance.value.export_price_estimated
    assert all(i.actual_kwh == 0 for i in day.intervals if i.start.hour in (0, 1, 2, 3, 20, 21, 22))


def test_consumption_on_device_days_adds_back_what_panels_covered(db, house):
    day = detail(db, house, DEMO_DAY)

    document_consumption = defaultdict(float)
    for interval in day.intervals:
        document_consumption[interval.start.hour] += interval.consumption_kwh or 0
    midday = sum(document_consumption[hour] for hour in range(9, 13))
    assert midday > 0
    assert day.consumption_kwh > day.balance.import_kwh


def test_dst_day_from_devices_has_100_quarters_each_with_its_own_value(db, house):
    day = detail(db, house, dt.date(2026, 10, 25))

    assert len(day.intervals) == 100
    assert all(i.consumption_kwh is not None for i in day.intervals)
    assert sum(i.consumption_kwh for i in day.intervals) == pytest.approx(day.consumption_kwh, abs=0.01)


def test_dst_day_from_meter_splits_the_repeated_hour_evenly():
    quarters = [dt.datetime(2026, 10, 24, 22, 0, tzinfo=UTC) + dt.timedelta(minutes=15 * i) for i in range(100)]
    readings = {}
    for moment in quarters:
        readings.setdefault(_naive_local(moment), (0.4, 0.0, "plik"))

    day = meter_day(quarters, readings, {}, files_with_export={"plik"})

    repeated = [day.consumption[dt.datetime(2026, 10, 25, hour, 0, tzinfo=UTC)] for hour in (0, 1)]
    assert len(day.consumption) == 100
    assert repeated == [pytest.approx(0.2), pytest.approx(0.2)]
    assert day.consumption[quarters[0]] == pytest.approx(0.4)


def test_future_day_uses_forecast_and_typical_consumption_with_estimated_export_price(db, house):
    tomorrow = dt.date(2026, 11, 24)
    add_weather(db, tomorrow)
    for back in range(1, 4):
        add_rce(db, tomorrow - dt.timedelta(days=back))

    day = detail(db, house, tomorrow)

    assert (day.kind, day.consumption_source, day.actual_kwh) == ("future", "typical", None)
    assert day.model_kwh > 5
    assert (day.typical.kind, day.typical.last_day) == ("workday", dt.date(2026, 10, 30))
    assert day.typical.days == 22
    assert day.balance.value.export_price_estimated
    assert day.balance.value.export_price == pytest.approx(0.5 * 1.23)
    assert any("14 poprzednich dni" in note for note in day.notes)


def test_net_metering_values_export_as_discount_on_grid_price(db, house):
    metering = {"mode": "net_metering", "installation": PV["installation"]}

    day = detail(db, house, DEMO_DAY, _profile(metering))

    assert day.balance.value.export_price == pytest.approx(0.8)


def test_rcem_contract_without_published_rcem_says_export_is_valued_by_rce(db, house):
    from app.models.RcEmPriceObservation import RcEmPriceObservation

    db.query(RcEmPriceObservation).filter(RcEmPriceObservation.price_month == DEMO_DAY.replace(day=1)).delete()
    db.commit()
    add_rce(db, DEMO_DAY)
    rcem = {**PV, "type_of_price": "RCEm"}

    rcem_day = detail(db, house, DEMO_DAY, _profile(rcem))
    rce_day = detail(db, house, DEMO_DAY)

    assert rcem_day.balance.value.export_price == pytest.approx(0.5 * 1.23)
    assert any("RCEm za ten miesiąc nie jest jeszcze opublikowana" in note for note in rcem_day.notes)
    assert not any("RCEm" in note for note in rce_day.notes)


def test_rcem_contract_without_any_price_for_the_day_explains_both(db, house):
    tomorrow = dt.date(2026, 11, 24)
    add_weather(db, tomorrow)
    for back in range(1, 4):
        add_rce(db, tomorrow - dt.timedelta(days=back))

    day = detail(db, house, tomorrow, _profile({**PV, "type_of_price": "RCEm"}))

    assert day.balance.value.export_price_estimated
    assert any(note.startswith("RCEm za ten miesiąc") and "14 poprzednich dni" in note for note in day.notes)


def test_data_periods_merge_touching_files_and_keep_gaps(db, house):
    files = EnergyDataFileRepository(db)
    for name, start, end in [("czerwiec.json", dt.date(2026, 6, 1), dt.date(2026, 6, 30)),
                             ("lipiec.csv", dt.date(2026, 7, 1), dt.date(2026, 7, 10)),
                             ("pazdziernik.json", dt.date(2026, 10, 20), dt.date(2026, 11, 5))]:
        energy_file = files.create(user_id=house.id, file_name=name)
        energy_file.status = EnergyDataFile.STATUS_COMPLETED
        energy_file.source_type = EnergyDataFile.SOURCE_METER
        energy_file.data_start, energy_file.data_end = start, end
        files.save(energy_file)
    db.commit()

    assert service(db).data_periods(house.id) == [
        (dt.date(2026, 6, 1), dt.date(2026, 7, 10)),
        (dt.date(2026, 10, 1), dt.date(2026, 11, 5)),
    ]


def test_without_tariff_rates_balance_has_no_value(db, house):
    from app.services.schedule_prices import NoTariffRatesError

    insights = service(db)

    def no_rates(*args, **kwargs):
        raise NoTariffRatesError("PGE, G11", "Brak stawek taryfy G11 u operatora PGE dla wybranego okresu.", False)

    insights.prices.for_user = no_rates
    profile = UserProfile.model_validate(_profile())
    day = insights.day(house.id, profile, insights.setup(house.id, profile), DEMO_DAY)

    assert day.balance is not None and day.balance.value is None
    assert any("Bez wyceny" in note and "Brak stawek" in note for note in day.notes)


def test_hours_without_grid_price_are_reported(db, house):
    insights = service(db)
    original = insights.prices.for_user

    def half_priced(user_id, start, end, **kwargs):
        result = original(user_id, start, end, **kwargs)
        prices = {moment: price for moment, price in result.prices.items() if moment.hour < 11}
        return type(result)(**{**vars(result), "prices": prices})

    insights.prices.for_user = half_priced
    profile = UserProfile.model_validate(_profile())
    day = insights.day(house.id, profile, insights.setup(house.id, profile), DEMO_DAY)

    assert any("Bez ceny z sieci dla części godzin" in note for note in day.notes)
    assert day.balance.value.self_pln < day.balance.self_kwh


def test_export_without_any_rce_prices_is_not_valued(db, house):
    day = detail(db, house, DEMO_DAY)

    assert day.balance.export_kwh > 0
    assert (day.balance.value.export_price, day.balance.value.export_pln) == (None, 0.0)
    assert not day.balance.value.export_price_estimated
    assert any("nie wyceniamy" in note for note in day.notes)


def test_house_without_files_shows_production_without_balance(db, house, user_b):
    db.add(UserProfileRow(user_id=user_b.id, **_profile()))
    db.commit()

    day = detail(db, user_b, DEMO_DAY)

    assert day.balance is None and day.consumption_source is None and day.actual_kwh is None
    assert day.model_kwh > 5


def test_day_without_weather_and_file_is_unavailable(db, house):
    from app.services.pv_forecast import PvForecastUnavailableError

    with pytest.raises(PvForecastUnavailableError):
        detail(db, house, dt.date(2026, 6, 1))


def test_past_day_without_readings_has_no_made_up_consumption(db, house):
    day_without_files = dt.date(2026, 11, 10)
    add_weather(db, day_without_files, "archive")

    day = detail(db, house, day_without_files)

    assert (day.kind, day.consumption_source, day.consumption_kwh, day.balance) == ("past", None, None, None)
    assert all(i.consumption_kwh is None for i in day.intervals)
    assert day.model_kwh > 0


def test_typical_consumption_is_not_guessed_from_old_files(db, house):
    later = dt.datetime(2027, 1, 10, 10, 0, tzinfo=UTC)
    add_weather(db, later.date())

    day = detail(db, house, later.date(), now=later)

    assert (day.consumption_source, day.typical, day.balance) == (None, None, None)


def test_same_devices_file_uploaded_twice_is_not_counted_twice(db, house):
    before = detail(db, house, DEMO_DAY)
    files = EnergyDataFileRepository(db)
    copy = files.create(user_id=house.id, file_name="dom-kopia.json")
    with DEVICES_DEMO.open("rb") as handle:
        parsed = parse_energy_file(handle)
    DeviceRepository(db).save_for_file(user_id=house.id, energy_data_file_id=copy.id, devices=parsed.devices)
    copy.status, copy.source_type = EnergyDataFile.STATUS_COMPLETED, EnergyDataFile.SOURCE_DEVICES
    copy.data_start, copy.data_end = dt.date(2026, 10, 1), dt.date(2026, 10, 30)
    files.save(copy)
    db.commit()
    clear_calibrations()

    after = detail(db, house, DEMO_DAY)

    assert after.actual_kwh == pytest.approx(before.actual_kwh)
    assert after.consumption_kwh == pytest.approx(before.consumption_kwh)


def test_file_data_for_today_and_future_is_ignored(db, house):
    late_now = dt.datetime(2026, 10, 13, 6, 0, tzinfo=UTC)

    day = detail(db, house, DEMO_DAY, now=late_now)

    assert (day.kind, day.actual_kwh, day.consumption_source) == ("today", None, "typical")


@pytest.fixture
def pv_api(db):
    app.dependency_overrides[get_pv_insights_service] = lambda: service(db)
    yield
    app.dependency_overrides.pop(get_pv_insights_service, None)


def test_pv_screen_endpoints(db, house, client_a, pv_api):
    overview = client_a.get("/api/v1/pv/overview")
    day = client_a.get("/api/v1/pv/day", params={"date": DEMO_DAY.isoformat()})
    accuracy = client_a.get("/api/v1/pv/accuracy")

    assert overview.status_code == 200
    body = overview.json()
    assert body["installation"]["total_kwp"] == 6.0 and body["installation"]["settlement"] == "net_billing"
    assert [d["date"] for d in body["days"]] == ["2026-11-23", "2026-11-24", "2026-11-25"]
    assert (body["first_data_day"], body["last_data_day"]) == ("2026-10-01", "2026-10-30")
    assert body["data_periods"] == [{"first_day": "2026-10-01", "last_day": "2026-10-30"}]
    assert body["calibration"]["candidate_days"] >= body["calibration"]["days"] > 0
    assert body["calibration"]["source"] == "history" and "peak" not in body["days"][0]
    assert day.status_code == 200 and len(day.json()["intervals"]) == 96 and day.json()["kind"] == "past"
    assert accuracy.status_code == 200 and len(accuracy.json()["days"]) == 30
    assert accuracy.json()["days_without_weather"] == 0
    assert "peak" not in day.json()


def test_pv_screen_endpoint_errors(db, house, client_a, client_b, anonymous_client, pv_api):
    assert client_a.get("/api/v1/pv/day", params={"date": "2026-11-26"}).status_code == 422
    assert client_a.get("/api/v1/pv/day", params={"date": "2026-06-01"}).status_code == 503
    assert client_b.get("/api/v1/pv/overview").status_code == 404
    assert anonymous_client.get("/api/v1/pv/overview").status_code == 401
    row = db.get(UserProfileRow, house.id)
    row.pv_config = {"mode": "none"}
    db.commit()
    assert client_a.get("/api/v1/pv/overview").status_code == 404
    assert client_a.get("/api/v1/pv/accuracy").status_code == 404

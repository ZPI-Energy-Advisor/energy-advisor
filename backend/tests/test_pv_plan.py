# ruff: noqa: F811 (fikstury db i home są parametrami testów)
"""ZP-121: plan na jutro z prognozowaną nadwyżką PV – rachunek godzinowy, wycena oddania, harmonogram i plan."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import Depends

from app.api.v1.deps import get_plan_service
from app.database import get_db
from app.repositories.day_plan_repository import DayPlanRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.home_repository import HomeRepository
from app.repositories.planning_repository import PlanningRepository
from app.repositories.user_repository import UserRepository
from app.repositories.weather_repository import WeatherRepository
from app.schemas.other import TypeOfMarketEnergyEnum
from app.services.day_background import DayBackground, DayBackgroundService
from app.services.heat_pump import HeatPumpService
from app.services.plan_service import PlanService
from app.services.prosumer import ExportValuation
from app.services.pv_balance import HouseBalance, by_slot
from app.services.pv_forecast import PvForecastService
from app.services.schedule_prices import SchedulePrices
from app.services.scheduling import SHIFTABLE, ScheduleAction, schedule
from app.services.weather_service import WeatherService
from main import app
from test_day_background import _house, _Offline, _weather_day, weather_cell  # noqa: F401 (fixture)
from test_day_plan import PLAN_DATE, _PriceRange
from test_energy_files import _headers, client
from test_home import db  # noqa: F401 (fixture)
from test_home_control import home  # noqa: F401 (fixture)
from test_plan_run import _by_device, _pv_action, _start
from test_planning_preferences import _put, _windows

UTC = timezone.utc
NOW = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
HOUR = datetime(2026, 10, 12, 10, tzinfo=UTC)
Q = timedelta(minutes=15)


def _quarters(hour, values):
    return {hour + index * Q: value for index, value in enumerate(values)}


def _balance(production_kwh=0.0, base=0.0, buy=1.0, sell=0.3):
    hours = [HOUR + timedelta(hours=offset) for offset in range(-2, 4)]
    prices = {hour + index * Q: buy for hour in hours for index in range(4)}
    production = _quarters(HOUR, [production_kwh / 4] * 4) if production_kwh else {}
    return HouseBalance({slot: base for slot in prices}, production, prices, {HOUR: sell})


# Rachunek godzinowy


def test_without_production_device_costs_energy_times_price():
    balance = _balance(production_kwh=0.0)

    assert balance.delta({}, {HOUR: 0.8, HOUR + Q: 0.4}) == pytest.approx(1.2)
    costs, total = balance.allocate([("pralka", HOUR, [0.8, 0.4])])
    assert costs == {"pralka": pytest.approx(1.2)} and total == pytest.approx(1.2)


def test_device_in_surplus_costs_only_lost_export():
    balance = _balance(production_kwh=2.0)

    assert balance.delta({}, {HOUR: 0.5, HOUR + Q: 0.5}) == pytest.approx(1.0 * 0.3)


def test_surplus_smaller_than_device_is_partly_from_grid():
    balance = _balance(production_kwh=0.4)

    # 0,4 kWh z paneli (traci oddanie po 0,30 zł) i 0,6 kWh z sieci po 1 zł.
    assert balance.delta({}, {HOUR: 1.0}) == pytest.approx(0.4 * 0.3 + 0.6 * 1.0)


def test_rest_of_home_uses_panels_first():
    balance = _balance(production_kwh=2.0, base=0.4)

    # Reszta domu bierze 1,6 kWh z 2 kWh w tej godzinie, więc pralce zostaje 0,4 kWh nadwyżki.
    assert balance.delta({}, {HOUR: 1.0}) == pytest.approx(0.4 * 0.3 + 0.6 * 1.0)


def test_allocation_splits_hour_change_between_devices_and_sums_to_total():
    balance = _balance(production_kwh=1.0)

    costs, total = balance.allocate([("pralka", HOUR, [0.6]), ("zmywarka", HOUR + Q, [0.6])])

    assert total == pytest.approx(1.0 * 0.3 + 0.2 * 1.0)
    assert costs["pralka"] == pytest.approx(total / 2) and costs["zmywarka"] == pytest.approx(total / 2)


def test_summary_counts_self_consumption_export_and_plan_share():
    balance = _balance(production_kwh=2.0, base=0.1)

    summary = balance.summary(by_slot([(HOUR, [0.5, 0.5])]))

    assert summary.self_kwh == pytest.approx(1.4)
    assert summary.export_kwh == pytest.approx(0.6)
    assert summary.plan_from_pv_kwh == pytest.approx(1.4 * 1.0 / 1.4)
    assert summary.export_pln == pytest.approx(0.6 * 0.3)


def test_hours_and_item_shares_follow_the_hourly_bill():
    balance = _balance(production_kwh=2.0, base=0.1)
    items = [("pralka", HOUR, [0.5, 0.5]), ("auto", HOUR + 2 * Q, [0.4])]

    hour, = balance.hours(by_slot((start, profile) for _, start, profile in items))
    shares = balance.from_pv(items)

    assert (hour.production_kwh, hour.rest_kwh, hour.plan_kwh) == (pytest.approx(2.0), pytest.approx(0.4), pytest.approx(1.4))
    assert hour.surplus_kwh == pytest.approx(1.6) and hour.export_kwh == pytest.approx(0.2)
    assert shares == {"pralka": pytest.approx(1.0), "auto": pytest.approx(0.4)}
    summary = balance.summary(by_slot((start, profile) for _, start, profile in items))
    assert sum(shares.values()) == pytest.approx(summary.plan_from_pv_kwh)


def test_effective_prices_make_surplus_quarters_cheap_for_boiler():
    balance = _balance(production_kwh=2.0, base=0.0)
    prices = {HOUR + index * Q: 1.0 for index in range(8)}

    effective = balance.effective_prices(prices, 0.5)

    assert [effective[HOUR + index * Q] for index in range(8)] == [0.3] * 4 + [1.0] * 4


# Wycena oddania


class _Market:
    """RCE w zł/kWh (bez × 1,23) i opcjonalnie RCEm; brak ceny = ValueError jak w resolverze."""

    def __init__(self, rce=None, rcem=None, rce_days=None):
        self.rce, self.rcem, self.rce_days = rce, rcem, rce_days

    def __call__(self, timestamp, price_type):
        if price_type == TypeOfMarketEnergyEnum.RCEm:
            if self.rcem is None:
                raise ValueError("brak RCEm")
            return self.rcem
        if self.rce is None or (self.rce_days is not None and timestamp.date() not in self.rce_days):
            raise ValueError("brak RCE")
        return self.rce

    def rcem_published(self, day):
        return self.rcem is not None


def _profile(mode="net_billing", price="RCE", k=None):
    return SimpleNamespace(pv_config=SimpleNamespace(
        mode=mode, type_of_price=TypeOfMarketEnergyEnum(price), effective_k_factor=k,
    ))


def test_net_billing_export_is_rce_times_deposit_coefficient():
    price, estimated = ExportValuation(_Market(rce=0.4), _profile()).hour_price(HOUR, 1.0)

    assert (price, estimated) == (pytest.approx(0.4 * 1.23), False)


def test_negative_rce_is_worth_nothing():
    price, _ = ExportValuation(_Market(rce=-0.2), _profile()).hour_price(HOUR, 1.0)

    assert price == 0.0


def test_rcem_contract_uses_rcem_and_rce_until_it_is_published():
    published = ExportValuation(_Market(rce=0.4, rcem=0.25), _profile(price="RCEm"))
    unpublished = ExportValuation(_Market(rce=0.4), _profile(price="RCEm"))

    assert published.hour_price(HOUR, 1.0)[0] == pytest.approx(0.25 * 1.23)
    assert unpublished.rcem_replaced(HOUR.date()) and not published.rcem_replaced(HOUR.date())


def test_without_prices_for_the_day_export_is_average_of_previous_days():
    market = _Market(rce=0.5, rce_days={HOUR.date() - timedelta(days=back) for back in range(1, 4)})

    price, estimated = ExportValuation(market, _profile()).hour_price(HOUR, 1.0)

    assert (price, estimated) == (pytest.approx(0.5 * 1.23), True)


def test_net_metering_export_is_discount_on_purchase_price():
    price, estimated = ExportValuation(None, _profile(mode="net_metering", k=0.8)).hour_price(HOUR, 1.1)

    assert (price, estimated) == (pytest.approx(0.88), False)


# Harmonogram


def _washer(start: datetime, starts: list[datetime]) -> ScheduleAction:
    return ScheduleAction(action_id="pralka", device_id="dev_wm_01", start=start, profile_kwh=[0.5, 0.5, 0.5, 0.5],
                          mode=SHIFTABLE, allowed_starts=frozenset(starts))


def test_washer_moves_into_surplus_even_with_flat_price():
    start = HOUR - timedelta(hours=2)
    starts = [start + index * Q for index in range(0, 17)]
    balance = _balance(production_kwh=3.0)

    flat = schedule([_washer(start, starts)], balance.buy)
    with_pv = schedule([_washer(start, starts)], balance.buy, balance=balance)

    assert flat.actions[0].start == start
    assert with_pv.actions[0].start == HOUR


def test_without_production_plan_is_the_same_as_without_pv():
    start = HOUR - timedelta(hours=2)
    starts = [start + index * Q for index in range(0, 17)]
    prices = {slot: (0.4 if slot.hour == 11 else 1.0) for slot in _balance().buy}
    balance = HouseBalance({}, {}, prices, {})

    plain = schedule([_washer(start, starts)], prices)
    with_balance = schedule([_washer(start, starts)], prices, balance=balance)

    assert [(a.start, a.cost_after) for a in plain.actions] == [(a.start, a.cost_after) for a in with_balance.actions]


def test_ev_charges_first_from_surplus():
    from app.services.scheduling import INTERRUPTIBLE

    balance = _balance(production_kwh=2.0)
    session = ScheduleAction(
        action_id="auto", device_id="dev_ev_01", start=HOUR - timedelta(hours=2), profile_kwh=[0.9] * 2,
        mode=INTERRUPTIBLE, window_start=HOUR - timedelta(hours=2), window_end=HOUR + timedelta(hours=2),
        max_slot_kwh=0.9,
    )

    result = schedule([session], balance.buy, balance=balance)

    planned = result.actions[0]
    used = {planned.start + index * Q for index, kwh in enumerate(planned.profile_kwh) if kwh}
    assert used <= {HOUR + index * Q for index in range(4)}


# Plan przez API


class _FlatPrices:
    """G11: 1 zł przez całą dobę, więc bez PV przesuwanie nic nie daje."""

    dynamic = False

    def for_user(self, user_id, start, end, exports=None):
        prices, slot = {}, start
        while slot < end:
            prices[slot] = 1.0
            slot += Q
        return SchedulePrices(prices=prices, description="TAURON, G11", dynamic=False)


def _sunny_afternoon(db, day: date, sun_w_m2: float = 700.0):
    """Słońce 10:00–14:00 UTC (12:00–16:00 w Polsce), czyli po zwykłej godzinie prania (10:00)."""
    from app.providers.prices.base import local_day_bounds_utc
    from app.providers.weather import WeatherPoint
    from test_day_background import CELL

    start, end = local_day_bounds_utc(day)
    points, moment = [], start
    while moment < end:
        sun = sun_w_m2 if 10 <= moment.hour < 14 else 0.0
        points.append(WeatherPoint(moment, 15, 10.0, 20, sun, {"35/0": sun}))
        moment += Q
    WeatherRepository(db).upsert(CELL.latitude, CELL.longitude, "forecast", points, NOW)


def _service(session, market):
    weather = WeatherService(WeatherRepository(session), client=_Offline(), now=lambda: NOW)
    heat_pumps = HeatPumpService(weather, DeviceRepository(session))
    return PlanService(
        PlanningRepository(session), DayPlanRepository(session), _FlatPrices(), _PriceRange(), today=lambda: PLAN_DATE,
        heat_pumps=heat_pumps,
        background=DayBackgroundService(
            HomeRepository(session), UserRepository(session).valid_profile,
            PvForecastService(weather, DeviceRepository(session)), heat_pumps,
        ),
        market=market,
    )


def _plan(owner, market, devices=None):
    assert _put(owner, {"devices": devices or [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
    ]}).status_code == 200
    app.dependency_overrides[get_plan_service] = lambda session=Depends(get_db): _service(session, market)
    try:
        response = client.post("/api/v1/planning/plans", json={"plan_date": PLAN_DATE.isoformat()}, headers=_headers(owner))
    finally:
        app.dependency_overrides.pop(get_plan_service, None)
    assert response.status_code == 201, response.text
    return response.json()


def test_sunny_day_moves_washer_into_panel_hours_even_on_g11(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])
    _weather_day(db, date(2026, 10, 5), "archive", 14.0, 300.0, NOW)
    _sunny_afternoon(db, PLAN_DATE)

    plan = _plan(owner, _Market(rce=0.3))

    washer, = plan["items"]
    start = datetime.fromisoformat(washer["start"]).astimezone(UTC)
    assert 10 <= start.hour < 14, washer["start"]
    assert washer["status"] == "moved"
    assert washer["cost_after"] < washer["cost_before"]
    assert plan["cost_after"] == pytest.approx(washer["cost_after"], abs=0.01)
    assert plan["saving"] == pytest.approx(plan["cost_before"] - plan["cost_after"], abs=0.01)
    pv = plan["pv"]
    assert pv["uncertainty"] == 0.2 and pv["uncertainty_source"] == "default"
    assert pv["planned_kwh"] == pytest.approx(pv["forecast_kwh"] * 0.8, abs=0.02)
    assert pv["after"]["plan_from_pv_kwh"] > pv["before"]["plan_from_pv_kwh"]
    assert pv["after"]["export_kwh"] < pv["before"]["export_kwh"]
    assert any(note.startswith("Prąd z paneli w poniedziałek 12 października: prognoza") for note in plan["notes"])
    hours = pv["hours"]
    assert [hour["start"][11:16] for hour in hours] == ["12:00", "13:00", "14:00", "15:00"]
    assert sum(hour["planned_kwh"] for hour in hours) == pytest.approx(pv["planned_kwh"], abs=0.02)
    assert sum(hour["forecast_kwh"] for hour in hours) == pytest.approx(pv["forecast_kwh"], abs=0.02)
    assert sum(hour["export_kwh"] for hour in hours) == pytest.approx(pv["after"]["export_kwh"], abs=0.02)
    assert sum(hour["plan_kwh"] for hour in hours) == pytest.approx(washer["energy_kwh"], abs=0.01)
    assert all(hour["surplus_kwh"] >= hour["export_kwh"] for hour in hours)
    assert washer["pv_kwh"] == pytest.approx(pv["after"]["plan_from_pv_kwh"], abs=0.01) and washer["pv_kwh"] > 0
    weather = plan["weather"]
    assert weather["past"] is False and weather["approximate_location"] is False
    assert len(weather["quarters"]) == 96
    noon = next(q for q in weather["quarters"] if q["start"][11:16] == "12:00")
    assert (noon["temperature_c"], noon["cloud_cover_pct"]) == (10.0, 20)
    assert weather["fetched_at"] == pv["weather_fetched_at"] == "2026-10-11T12:00:00+02:00"
    stored = DayBackground.from_json({"weather": {"fetched_at": None, "approximate_location": True, "quarters": []}})
    assert DayBackground.from_json(stored.to_json()).weather["approximate_location"] is True


def test_export_worth_more_than_grid_keeps_washer_out_of_surplus(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])
    _weather_day(db, date(2026, 10, 5), "archive", 14.0, 300.0, NOW)
    _sunny_afternoon(db, PLAN_DATE)

    plan = _plan(owner, _Market(rce=1.2))

    washer, = plan["items"]
    # Oddanie warte 1,2 × 1,23 zł, a prąd z sieci 1 zł: pranie z paneli traci więcej, niż kosztuje sieć.
    assert washer["status"] == "unchanged"


def test_no_weather_plans_without_panels_and_says_so(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])

    plan = _plan(owner, _Market(rce=0.3))

    assert plan["pv"] is None and plan["weather"] is None and plan["pv_reason"] == "no_weather"
    assert plan["items"][0]["status"] == "unchanged" and plan["items"][0]["pv_kwh"] is None
    assert any("nie liczy na prąd z paneli" in note for note in plan["notes"])


def test_profile_without_panels_plans_like_before(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)], pv_config={"mode": "none"})
    _weather_day(db, PLAN_DATE, "forecast", 10.0, 700.0, NOW)

    plan = _plan(owner, _Market(rce=0.3))

    washer, = plan["items"]
    assert plan["pv"] is None
    assert (washer["status"], washer["cost_before"]) == ("unchanged", pytest.approx(1.4))
    assert len(plan["weather"]["quarters"]) == 96 and plan["weather"]["quarters"][0]["temperature_c"] == 10.0
    assert plan["pv_reason"] == "no_installation"


def test_simulation_report_uses_plan_pv_costs(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])
    _weather_day(db, date(2026, 10, 5), "archive", 14.0, 300.0, NOW)
    _sunny_afternoon(db, PLAN_DATE)
    plan = _plan(owner, _Market(rce=0.3))
    assert client.post(f"/api/v1/planning/plans/{plan['id']}/approve", headers=_headers(owner)).status_code == 200

    run = _start(owner, plan["id"]).json()

    action, = run["devices"][0]["actions"]
    washer, = plan["items"]
    assert action["cost_before"] == pytest.approx(washer["cost_before"])
    assert action["planned_cost"] == pytest.approx(washer["cost_after"])
    assert "dev_wm_01" in _by_device(home.hub.batches[0])


def test_day_without_surplus_says_plan_follows_grid_prices_only():
    from app.services.plan_service import _PlanPv
    from app.services.pv_balance import Summary

    pv = _PlanPv(
        balance=_balance(production_kwh=1.0), forecast={"total_kwh": 1.3}, uncertainty=0.04,
        uncertainty_source="history", settlement="net_billing", export_estimated=False, export_unpriced=False,
        rcem_replaced=False, plan_date=date(2026, 11, 27),
        before=Summary(self_kwh=1.2, plan_from_pv_kwh=0.4), after=Summary(self_kwh=1.2, plan_from_pv_kwh=0.2),
    )

    notes = pv.notes()

    assert notes[0].startswith("Prąd z paneli w piątek 27 listopada: prognoza 1,3 kWh. Plan liczy na 1,0 kWh")
    assert "o 4% mniej (tyle średnio myli się prognoza dla Twoich paneli)" in notes[0]
    assert notes[1].startswith("Nadwyżki z paneli nie będzie")


# Reszta domu z licznika


def _local_quarters(day: date):
    from app.providers.prices.base import MARKET_TIMEZONE, local_day_bounds_utc

    start, end = local_day_bounds_utc(day)
    moment = start
    while moment < end:
        yield moment, moment.astimezone(MARKET_TIMEZONE).replace(tzinfo=None)
        moment += Q


def test_rest_of_home_comes_from_meter_when_device_file_has_only_flexible_devices():
    from app.services.house_load import rest_of_home

    day = date(2026, 10, 5)
    readings = {local: (0.5, 0.0, "licznik") for _, local in _local_quarters(day)}
    washer = [(utc, 0.2) for utc, local in _local_quarters(day) if local.hour == 10]

    rest, source = rest_of_home([], washer, readings, set(), {}, 7)

    assert source == "meter"
    assert rest[10 * 60] == pytest.approx(0.3) and rest[3 * 60] == pytest.approx(0.5)


def test_complete_device_file_gives_the_same_as_before():
    from app.services.house_load import rest_of_home

    day = date(2026, 10, 5)
    fixed = [(utc, 0.1) for utc, _ in _local_quarters(day)]

    rest, source = rest_of_home(fixed, [], {}, set(), {}, 7)

    assert source == "devices" and rest[12 * 60] == pytest.approx(0.1)


def test_meter_adds_back_panel_production_used_at_home():
    from app.services.house_load import rest_of_home

    day = date(2026, 10, 5)
    readings = {local: (0.1, 0.0, "licznik") for _, local in _local_quarters(day)}
    production = {day: {utc: 0.4 for utc, local in _local_quarters(day) if 10 <= local.hour < 14}}

    rest, _ = rest_of_home([], [], readings, {"licznik"}, production, 7)

    # Licznik widzi 0,1 kWh poboru, ale dom zużył też 0,4 kWh z paneli.
    assert rest[11 * 60] == pytest.approx(0.5) and rest[20 * 60] == pytest.approx(0.1)


def _meter_file(db, owner, day: date, used_kwh: float, hours: range):
    from app.models.EnergyDataFile import EnergyDataFile
    from app.repositories.energy_data_file_repository import EnergyDataFileRepository
    from app.repositories.energy_reading_repository import EnergyReadingRepository

    files = EnergyDataFileRepository(db)
    meter = files.create(user_id=owner.id, file_name="licznik.csv")
    meter.status, meter.source_type = EnergyDataFile.STATUS_COMPLETED, EnergyDataFile.SOURCE_METER
    meter.data_start = meter.data_end = day
    files.save(meter)
    readings = [(local, used_kwh if local.hour in hours else 0.05, 0.0) for _, local in _local_quarters(day)]
    EnergyReadingRepository(db).replace_for_file(meter.id, readings)
    db.commit()


def test_house_that_uses_its_own_sun_does_not_move_washer_into_it(db, home, weather_cell):
    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)])
    _weather_day(db, date(2026, 10, 5), "archive", 14.0, 300.0, NOW)
    _sunny_afternoon(db, PLAN_DATE)
    # Licznik: w godzinach słońca (12:00–16:00 w Polsce) dom pobiera z sieci 1 kWh na kwadrans, więc panele
    # zjada reszta domu (np. kuchnia, praca z domu), a pralka nie ma z czego brać.
    _meter_file(db, owner, date(2026, 10, 5), 1.0, range(12, 16))

    plan = _plan(owner, _Market(rce=0.3))

    washer, = plan["items"]
    assert plan["pv"]["rest_source"] == "meter"
    assert washer["status"] == "unchanged"
    assert any(note.startswith("Zwykłe zużycie reszty domu liczymy z licznika") for note in plan["notes"])


def _cold_sunny_day(db, day: date):
    from app.providers.prices.base import local_day_bounds_utc
    from app.providers.weather import WeatherPoint
    from test_day_background import CELL

    start, end = local_day_bounds_utc(day)
    points, moment = [], start
    while moment < end:
        sun = 800.0 if 10 <= moment.hour < 14 else 0.0
        points.append(WeatherPoint(moment, 15, 2.0, 10, sun, {"35/0": sun}))
        moment += Q
    WeatherRepository(db).upsert(CELL.latitude, CELL.longitude, "forecast", points, NOW)


def _sun_share(plan) -> float:
    total = sunny = 0.0
    for item in plan["items"]:
        if item["kind"] != "heat_pump":
            continue
        start = datetime.fromisoformat(item["start"]).astimezone(UTC)
        for index, kwh in enumerate(item["profile_kwh"]):
            total += kwh
            if 10 <= (start + index * Q).hour < 14:
                sunny += kwh
    return sunny / total


def test_heat_pump_heats_more_under_the_sun_with_panels(db, home, weather_cell):
    from app.models.UserProfile import UserProfile as UserProfileRow
    from test_home import HEAT_PUMP

    owner = _house(db, home, [_pv_action("2026-10-05", -6.4)], extra=[HEAT_PUMP])
    _weather_day(db, date(2026, 10, 5), "archive", 8.0, 300.0, NOW)
    _cold_sunny_day(db, PLAN_DATE)
    pump = [{"device_id": "dev_hp_01", "enabled": True, "shift_hours": 1}]

    with_panels = _plan(owner, _Market(rce=0.2), devices=pump)
    db.get(UserProfileRow, owner.id).pv_config = {"mode": "none"}
    db.commit()
    without_panels = _plan(owner, _Market(rce=0.2), devices=pump)

    assert with_panels["pv"] is not None and without_panels["pv"] is None
    assert _sun_share(with_panels) > _sun_share(without_panels)

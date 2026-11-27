# ruff: noqa: F811 (fikstury db, home i weather_cell są parametrami testów)
"""ZP-152: plan idealny dnia z przeszłości – dzień z plików i spoza plików, PV z archiwum, plan na jutro nienaruszony."""

from datetime import date

import pytest
from fastapi import Depends

from app.api.v1.deps import get_plan_service
from app.database import get_db
from app.models.DayPlan import DayPlan
from app.repositories.day_plan_repository import DayPlanRepository
from app.repositories.planning_repository import PlanningRepository
from app.services.plan_service import PlanService
from main import app
from test_day_background import _house, _weather_day, weather_cell  # noqa: F401 (fixture)
from test_day_plan import PLAN_DATE, WARSAW, _Prices, _PriceRange, _local, _owner
from test_energy_files import _headers, client
from test_home import WASHER, _upload, db  # noqa: F401 (db: fixture)
from test_home_control import home  # noqa: F401 (home: fixture)
from test_planning_preferences import DISHWASHER, EV, _put, _windows
from test_plan_run import _by_device, _file, _pv_action, _start
from test_pv_plan import NOW, _Market, _service

FILE_DAY = "2026-10-05"  # W plikach testowych pralka pierze 05.10 o 10:00, a auto ładuje się od 18:00.
OUTSIDE = "2026-09-01"


class _PricesFrom(_Prices):
    def first_priced_day(self, user_id):
        return date(2024, 8, 24), False


class _DynamicPrices(_PricesFrom):
    dynamic = True

    def price(self, slot):
        return None if slot.astimezone(WARSAW).date() == date(2026, 9, 1) else super().price(slot)

    def first_priced_day(self, user_id):
        return date(2024, 8, 24), True


def _call(method, path, user, body=None, prices=_PricesFrom, params=None):
    app.dependency_overrides[get_plan_service] = lambda session=Depends(get_db): PlanService(
        PlanningRepository(session), DayPlanRepository(session), prices(), _PriceRange(), today=lambda: PLAN_DATE,
    )
    try:
        if method == "post":
            return client.post(path, json=body or {}, headers=_headers(user))
        return client.get(path, params=params, headers=_headers(user))
    finally:
        app.dependency_overrides.pop(get_plan_service, None)


def _create(user, plan_date=None, prices=_PricesFrom):
    return _call("post", "/api/v1/planning/plans", user, {"plan_date": plan_date} if plan_date else None, prices)


def _settings(owner, *devices):
    assert _put(owner, {"devices": list(devices)}).status_code == 200


WASHER_SETTINGS = {"device_id": "dev_wm_01", "enabled": True, "program_id": "quick_30", "windows": _windows(("07:00", "22:00"))}
EV_SETTINGS = {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("18:00", "07:00")), "energy_kwh": 10}
DISHWASHER_SETTINGS = {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": _windows(("19:00", "07:00"))}
SECOND_DAY = "2026-10-06"


def _two_days(home):
    """Pliki z 05.10 i 06.10: 06.10 pierze tylko pralka, a zmywarka pracuje tylko 05.10."""
    washing = {**WASHER["actions"][0], "action_id": "act_wm_06",
               "action_start": f"{SECOND_DAY}T09:00:00+02:00", "action_end": f"{SECOND_DAY}T09:30:00+02:00"}
    period = {"start": "2026-10-05T00:00:00+02:00", "end": "2026-10-07T00:00:00+02:00"}
    content = _file(period, [WASHER["device"], DISHWASHER["device"]], [*WASHER["actions"], washing, *DISHWASHER["actions"]])
    assert _upload(home.owner, content).status_code == 200
    return home.owner


def test_file_day_starts_devices_like_that_day_and_moves_them_in_settings_windows(home):
    owner = _owner(home, WASHER, EV)
    _settings(owner, WASHER_SETTINGS, EV_SETTINGS)

    response = _create(owner, FILE_DAY)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["day_source"]) == ("past_day", "files")
    items = {item["device_id"]: item for item in body["items"]}
    # Bez planu: pralka o 10:00 i auto od 18:00, jak tego dnia w pliku; auto z energią z pliku, a nie z ustawień.
    assert _local(items["dev_wm_01"]["original_start"]).strftime("%H:%M") == "10:00"
    assert _local(items["dev_ev_01"]["original_start"]).strftime("%H:%M") == "18:00"
    assert sum(items["dev_ev_01"]["profile_kwh"]) == pytest.approx(3.6)
    assert sum(items["dev_ev_01"]["original_profile_kwh"]) == pytest.approx(3.6)
    # Plan przesuwa pralkę w tanie godziny z ustawień (13:00–15:00).
    assert 13 <= _local(items["dev_wm_01"]["start"]).hour < 15
    assert body["notes"][0].startswith("Plan idealny na 5 października: pogoda jest z archiwum, a zużycie reszty domu z plików")
    assert "(Pralka Bosch i Ładowarka EV)" in body["notes"][0]
    assert not any("startuje o godzinie, o której zwykle" in note for note in body["notes"])


def test_file_day_uses_the_program_that_ran_that_day(home):
    owner = _owner(home, WASHER)
    _settings(owner, {**WASHER_SETTINGS, "program_id": "cotton_60"})

    washer, = _create(owner, FILE_DAY).json()["items"]

    # W pliku 05.10 pralka prała programem quick_30, choć w ustawieniach jest cotton_60.
    assert washer["program_id"] == "quick_30"
    assert sum(washer["original_profile_kwh"]) == pytest.approx(sum(washer["profile_kwh"]))


def test_unticked_device_of_a_file_day_replays_that_very_day(home, db):
    from app.repositories.home_repository import HomeRepository
    from app.services.day_background import history_runs
    from test_home import HEAT_PUMP

    night = {**HEAT_PUMP["actions"][0], "action_id": "act_hp_night",
             "action_start": "2026-10-06T02:00:00+02:00", "action_end": "2026-10-06T03:00:00+02:00"}
    period = {"start": "2026-10-05T00:00:00+02:00", "end": "2026-10-07T00:00:00+02:00"}
    assert _upload(home.owner, _file(period, [HEAT_PUMP["device"]], [*HEAT_PUMP["actions"], night])).status_code == 200
    repository = HomeRepository(db)

    tomorrow_like, _ = history_runs(repository, home.owner.id, date(2026, 10, 6), ["dev_hp_01"])
    same_day, runs = history_runs(repository, home.owner.id, date(2026, 10, 6), ["dev_hp_01"], same_day=True)

    assert tomorrow_like["dev_hp_01"] == date(2026, 10, 5)
    assert same_day["dev_hp_01"] == date(2026, 10, 6)
    assert [run.ref for run in runs["dev_hp_01"]] == ["act_hp_night"]


def test_file_day_leaves_out_devices_that_did_not_work_that_day(home):
    owner = _two_days(home)
    _settings(owner, WASHER_SETTINGS, DISHWASHER_SETTINGS)

    body = _create(owner, SECOND_DAY).json()

    assert [item["device_id"] for item in body["items"]] == ["dev_wm_01"]
    assert _local(body["items"][0]["original_start"]).strftime("%H:%M") == "09:00"
    assert any("nie ma pracy: Zmywarka" in note for note in body["notes"])


def test_file_day_without_any_ticked_device_working_explains_it(home):
    owner = _two_days(home)
    _settings(owner, DISHWASHER_SETTINGS)

    response = _create(owner, SECOND_DAY)

    assert response.status_code == 422
    assert "nie pracowało żadne z zaznaczonych urządzeń" in response.json()["detail"]


def test_day_outside_files_uses_settings_and_says_so(home):
    owner = _owner(home, WASHER, EV)
    _settings(owner, WASHER_SETTINGS, EV_SETTINGS)

    body = _create(owner, OUTSIDE).json()

    assert (body["kind"], body["day_source"]) == ("past_day", "settings")
    items = {item["device_id"]: item for item in body["items"]}
    assert sum(items["dev_ev_01"]["profile_kwh"]) == pytest.approx(10)
    assert "Tego dnia nie ma w plikach urządzeń" in body["notes"][0]


def test_plan_for_tomorrow_stays_current_next_to_ideal_plan(home):
    owner = _owner(home, WASHER)
    _settings(owner, WASHER_SETTINGS)
    tomorrow = _create(owner).json()
    assert tomorrow["kind"] == "tomorrow" and tomorrow["day_source"] is None
    approved = client.post(f"/api/v1/planning/plans/{tomorrow['id']}/approve", headers=_headers(owner)).json()

    ideal = _create(owner, FILE_DAY).json()
    current = _call("get", "/api/v1/planning/plans/current", owner).json()
    by_date = _call("get", "/api/v1/planning/plans", owner, params={"date": FILE_DAY}).json()
    missing = _call("get", "/api/v1/planning/plans", owner, params={"date": "2026-09-30"}).json()

    assert (current["id"], current["status"]) == (tomorrow["id"], approved["status"]) == (tomorrow["id"], "approved")
    assert by_date["id"] == ideal["id"] and by_date["kind"] == "past_day"
    assert missing is None


def test_plan_from_before_kind_field_is_classified_by_its_creation_day(home, db):
    owner = _owner(home, WASHER)
    _settings(owner, WASHER_SETTINGS)
    ideal = _create(owner, FILE_DAY).json()
    stored = db.get(DayPlan, ideal["id"])
    stored.result = {key: value for key, value in stored.result.items() if key not in ("kind", "day_source")}
    db.commit()

    by_date = _call("get", "/api/v1/planning/plans", owner, params={"date": FILE_DAY}).json()

    assert by_date["kind"] == "past_day"
    assert _call("get", "/api/v1/planning/plans/current", owner).json() is None


def test_past_days_range_and_file_periods(home):
    owner = _owner(home, WASHER)

    static = _call("get", "/api/v1/planning/past-days", owner).json()
    dynamic = _call("get", "/api/v1/planning/past-days", owner, prices=_DynamicPrices).json()

    assert static == {"first_day": "2024-08-24", "last_day": "2026-10-10",
                      "file_periods": [{"first_day": "2026-10-05", "last_day": "2026-10-05"}]}
    # Cena dynamiczna: od pierwszego dnia z RCE w bazie (w testach 01.01.2026).
    assert dynamic["first_day"] == "2026-01-01"


def test_same_period_uploaded_twice_is_one_file_period(home):
    owner = _owner(home, WASHER)
    assert _upload(owner, _file(
        {"start": "2026-10-05T00:00:00+02:00", "end": "2026-10-08T00:00:00+02:00"}, [WASHER["device"]], WASHER["actions"],
    )).status_code == 200

    periods = _call("get", "/api/v1/planning/past-days", owner).json()["file_periods"]

    assert periods == [{"first_day": "2026-10-05", "last_day": "2026-10-07"}]


def test_day_without_prices_gives_message_instead_of_plan(home):
    owner = _owner(home, WASHER)
    _settings(owner, WASHER_SETTINGS)

    response = _create(owner, OUTSIDE, prices=_DynamicPrices)

    assert response.status_code == 422
    assert response.json()["detail"] == "Brak cen dynamicznych na 01.09.2026, więc planu idealnego na ten dzień nie ułożymy."


def _ideal_with_pv(db, home, market):
    owner = _house(db, home, [_pv_action(FILE_DAY, -6.4)])
    _weather_day(db, date(2026, 10, 5), "archive", 14.0, 500.0, NOW)
    _settings(owner, WASHER_SETTINGS)
    app.dependency_overrides[get_plan_service] = lambda session=Depends(get_db): _service(session, market)
    try:
        response = client.post("/api/v1/planning/plans", json={"plan_date": FILE_DAY}, headers=_headers(owner))
    finally:
        app.dependency_overrides.pop(get_plan_service, None)
    assert response.status_code == 201, response.text
    return owner, response.json()


def test_ideal_plan_uses_archive_weather_without_cutting_pv(db, home, weather_cell):
    _, plan = _ideal_with_pv(db, home, _Market(rce=0.3))

    pv = plan["pv"]
    assert (pv["uncertainty"], pv["uncertainty_source"]) == (0.0, "archive")
    assert pv["planned_kwh"] == pytest.approx(pv["forecast_kwh"], abs=0.01) and pv["forecast_kwh"] > 0
    assert plan["weather"]["past"] is True
    assert any("z pogody z archiwum" in note and "liczy na całą produkcję" in note for note in plan["notes"])


def test_ideal_plan_sends_the_same_pv_energy_to_the_hub(db, home, weather_cell):
    owner, plan = _ideal_with_pv(db, home, _Market(rce=0.3))
    assert client.post(f"/api/v1/planning/plans/{plan['id']}/approve", headers=_headers(owner)).status_code == 200

    run = _start(owner, plan["id"]).json()

    sent = -sum(sum(command["profile_kwh"]) for command in _by_device(home.hub.batches[0])["dev_pv_01"])
    assert sent == pytest.approx(plan["pv"]["planned_kwh"], rel=0.01)
    assert run["plan_kind"] == "past_day"
    history = client.get("/api/v1/home/plan-runs", headers=_headers(owner)).json()
    assert history[0]["plan_kind"] == "past_day"

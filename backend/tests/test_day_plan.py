# ruff: noqa: F811 (fikstury db i home z test_home są parametrami testów)
"""ZP-112: plan pracy urządzeń na jutro z ustawień ZP-111 – przydziały, koszty, ceny i statusy."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends

from app.api.v1.deps import get_plan_service
from app.database import get_db
from app.repositories.day_plan_repository import DayPlanRepository
from app.repositories.planning_repository import PlanningRepository
from app.services.plan_service import PlanService
from app.services.schedule_prices import SchedulePrices
from app.services.scheduling import SLOT
from main import app
from test_energy_files import _headers, client
from test_home import HEAT_PUMP, WASHER, _devices_file, _upload, db, home  # noqa: F401 (fixtures)
from test_planning_preferences import DISHWASHER, EV, WATER_HEATER, _put, _windows

WARSAW = ZoneInfo("Europe/Warsaw")
# Poniedziałek jak dzień historii w plikach (05.10), więc pompa i bojler biorą ten dzień.
PLAN_DATE = date(2026, 10, 12)
LATEST_PRICES = date(2026, 10, 11)


class _Prices:
    """Ceny każdego dnia: tanio 13:00–15:00 (0,2 zł) i 02:00–04:00 (0,3 zł), poza tym 1 zł."""

    dynamic = False

    def price(self, slot: datetime) -> float | None:
        hour = slot.astimezone(WARSAW).hour
        return 0.2 if 13 <= hour < 15 else 0.3 if 2 <= hour < 4 else 1.0

    def for_user(self, user_id, start, end, exports=None):
        prices, slot = {}, start
        while slot < end:
            price = self.price(slot)
            if price is not None:
                prices[slot] = price
            slot += SLOT
        return SchedulePrices(prices=prices, description="PGE, G11", dynamic=self.dynamic)


class _PricesWithGridLimit(_Prices):
    def for_user(self, user_id, start, end, exports=None):
        prices = super().for_user(user_id, start, end, exports)
        return SchedulePrices(prices=prices.prices, description=prices.description, max_grid_kw=5.0)


class _DynamicUntilPlanDay(_Prices):
    """Ceny dynamiczne opublikowane tylko do końca dnia planu: po północy ich nie ma."""

    dynamic = True

    def price(self, slot):
        return super().price(slot) if slot.astimezone(WARSAW).date() <= PLAN_DATE else None


class _DynamicUntilLatest(_Prices):
    """Ceny dynamiczne tylko do LATEST_PRICES: na dzień planu jeszcze nieopublikowane."""

    dynamic = True

    def price(self, slot):
        return super().price(slot) if slot.astimezone(WARSAW).date() <= LATEST_PRICES else None


class _PriceRange:
    def get_available_range(self, source):
        return date(2026, 1, 1), LATEST_PRICES, None


def _use_prices(prices=_Prices):
    def factory(session=Depends(get_db)):
        return PlanService(
            PlanningRepository(session), DayPlanRepository(session), prices(), _PriceRange(), today=lambda: PLAN_DATE,
        )

    app.dependency_overrides[get_plan_service] = factory


def _create(user, body=None, prices=_Prices):
    _use_prices(prices)
    try:
        return client.post("/api/v1/planning/plans", json=body or {}, headers=_headers(user))
    finally:
        app.dependency_overrides.pop(get_plan_service, None)


def _items(response) -> dict:
    return {item["action_id"]: item for item in response.json()["items"]}


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(WARSAW)


def _owner(home, *entries):
    entries = entries or (WASHER, DISHWASHER, EV, HEAT_PUMP, WATER_HEATER)
    assert _upload(home.owner, _devices_file(*entries)).status_code == 200
    return home.owner


def test_plan_puts_devices_in_cheapest_allowed_hours_as_draft(home):
    owner = _owner(home)
    assert _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("18:00", "07:00")), "energy_kwh": 5},
    ]}).status_code == 200

    response = _create(owner)

    assert response.status_code == 201
    body = response.json()
    assert (body["status"], body["plan_date"]) == ("draft", "2026-10-12")
    assert body["horizon_end"] == "2026-10-13T06:00:00+02:00"
    items = _items(response)
    # Pralka: bez planu jak zwykle (w historii o 10:00), w planie najtańsze 13:00–15:00.
    washer = items["dev_wm_01"]
    assert washer["original_start"] == "2026-10-12T10:00:00+02:00"
    assert 13 <= _local(washer["start"]).hour and _local(washer["end"]) <= datetime(2026, 10, 12, 15, tzinfo=WARSAW)
    assert washer["status"] == "moved"
    # Auto: 5 kWh w nocy po dniu planu, w tanich 02:00–04:00 (przedział do 07:00 przycięty do 06:00).
    ev = items["dev_ev_01"]
    assert ev["energy_kwh"] == 5
    assert datetime(2026, 10, 13, 2, tzinfo=WARSAW) <= _local(ev["start"])
    assert _local(ev["end"]) <= datetime(2026, 10, 13, 4, tzinfo=WARSAW)
    # Pompa ciepła: blok 12:00–13:00 z historii przesunięty najwyżej o 1 h, na tanie 13:00.
    assert items["dev_hp_01#1"]["start"] == "2026-10-12T13:00:00+02:00"
    assert items["dev_hp_01#1"]["program_name"] == "grzanie po południu"
    assert body["warnings"] == []
    # Bojler: grzeje tylko w tanich godzinach (na zapas), a woda jest ciepła na 06:00 i 18:00.
    heater = items["dev_wh_01"]
    assert heater["program_name"] == "woda gotowa na 06:00, 18:00"
    assert heater["cost_after"] < heater["cost_before"]
    assert all(_local(period["start"]).hour in (2, 3, 13, 14) for period in heater["charging"])
    # Termostat bez planu grzeje krótkimi porcjami: kilka okresów także w pracy bez planu.
    assert len(heater["original_charging"]) > 1
    water = body["water_heaters"][0]
    # Ciepła woda z historii bojlera: 3,6 kWh z termostatem minus jego straty (ok. 1,1 kWh), zbiornik 80 l.
    assert (water["hot_water_source"], water["hot_water_kwh"], water["tank_liters"]) == ("history", 2.48, 80)
    assert water["shortfall"] == 0
    temps = {_local(point["start"]).strftime("%d %H:%M"): point["after"] for point in water["temperatures"]}
    assert temps["12 05:45"] >= 55 and temps["12 17:45"] >= 55
    assert min(point["after"] for point in water["temperatures"]) >= 40
    # Bojler liczymy w dobie planu: plan od 45°C o północy, termostat od 55°C.
    assert len(water["temperatures"]) == 96
    assert (water["start_after"], water["start_before"]) == (45, 55)
    assert body["cost_after"] < body["cost_before"]
    assert body["saving"] == round(body["cost_before"] - body["cost_after"], 2)
    assert body["approximate_from"] is None
    assert len(body["prices"]) == 30 * 4


def test_run_after_starts_right_after_predecessor_and_respects_finish_time(home):
    owner = _owner(home, WASHER, DISHWASHER)
    assert _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
        {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "after_device_id": "dev_wm_01",
         "finish_by": "12:00"},
    ]}).status_code == 200

    items = _items(_create(owner))

    washer, dishwasher = items["dev_wm_01"], items["dev_dw_01"]
    assert dishwasher["start"] == washer["end"]
    assert dishwasher["program_name"] == "Eco, po: Pralka Bosch"
    # Zmywarka musi skończyć przed 12:00, więc łańcuch nie może pójść na tanie 13:00.
    assert _local(dishwasher["end"]) <= datetime(2026, 10, 12, 12, tzinfo=WARSAW)


def test_night_prices_of_dynamic_tariff_are_copied_from_plan_day_and_marked(home):
    owner = _owner(home, EV)
    assert _put(owner, {"devices": [
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("22:00", "06:00")), "energy_kwh": 5},
    ]}).status_code == 200

    response = _create(owner, prices=_DynamicUntilPlanDay)

    body = response.json()
    assert response.status_code == 201
    assert body["approximate_from"] == "2026-10-13T00:00:00+02:00"
    assert body["notes"][0].startswith("Ceny na noc po tym dniu nie są jeszcze znane")
    # Noc ma ceny z tych samych godzin dnia planu: tanie 02:00–04:00, więc auto ładuje się wtedy.
    ev = _items(response)["dev_ev_01"]
    assert datetime(2026, 10, 13, 2, tzinfo=WARSAW) <= _local(ev["start"])
    assert body["prices"][-1]["start"] == "2026-10-13T05:45:00+02:00"


def test_missing_dynamic_prices_explain_publication_and_allow_demo_day(home):
    owner = _owner(home, WASHER)
    assert _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "quick_30", "windows": _windows(("07:00", "22:00"))},
    ]}).status_code == 200

    missing = _create(owner, prices=_DynamicUntilLatest)
    demo = _create(owner, {"plan_date": "2026-10-10"}, prices=_DynamicUntilLatest)

    assert missing.status_code == 409
    detail = missing.json()["detail"]
    assert detail["code"] == "no_prices"
    assert "ok. 14:00" in detail["message"]
    assert detail["latest_price_date"] == "2026-10-11"
    assert demo.status_code == 201
    assert demo.json()["plan_date"] == "2026-10-10"


def test_plan_is_approved_and_recreating_returns_to_draft(home):
    owner = _owner(home, WASHER)
    assert _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "quick_30", "windows": _windows(("07:00", "22:00"))},
    ]}).status_code == 200
    plan_id = _create(owner).json()["id"]

    approved = client.post(f"/api/v1/planning/plans/{plan_id}/approve", headers=_headers(owner))
    current = client.get("/api/v1/planning/plans/current", headers=_headers(owner))
    foreign = client.post(f"/api/v1/planning/plans/{plan_id}/approve", headers=_headers(home.other))
    again = _create(owner)

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert current.json()["id"] == plan_id and current.json()["status"] == "approved"
    assert foreign.status_code == 404
    assert again.json()["id"] == plan_id and again.json()["status"] == "draft"
    assert client.get("/api/v1/planning/plans/current", headers=_headers(home.other)).json() is None


def test_plan_needs_an_enabled_device(home):
    owner = _owner(home, WASHER)

    response = _create(owner)

    assert response.status_code == 422
    assert response.json()["detail"] == "Zaznacz w ustawieniach co najmniej jedno urządzenie, które ma jutro pracować."


def test_ev_energy_beyond_plan_end_is_reported(home):
    owner = _owner(home, EV)
    # Ustawienia liczą pełny przedział 18:00–07:00 (13 h × 3,7 kW = 48,1 kWh), a plan kończy się o 06:00:
    # 12 h × 3,7 kW = 44,4 kWh, więc 0,6 kWh nie zmieści się w planie.
    assert _put(owner, {"devices": [
        {"device_id": "dev_ev_01", "enabled": True, "windows": _windows(("18:00", "07:00")), "energy_kwh": 45},
    ]}).status_code == 200

    response = _create(owner)

    assert _items(response)["dev_ev_01"]["energy_kwh"] == 44.4
    assert response.json()["warnings"] == ["Ładowarka EV: do 6:00 auto nie naładuje się do końca, zabraknie ok. 0,6 kWh."]


HOB = {
    "device": {
        "device_id": "dev_hob_01",
        "device_name": "Płyta indukcyjna",
        "device_type": "induction_hob",
        "device_category": "AGD",
        "max_power_kw": 4.0,
        "flexibility": {"mode": "fixed"},
    },
    "actions": [{
        "action_id": "act_hob_1", "device_id": "dev_hob_01",
        "action_start": "2026-10-05T13:00:00+02:00", "action_end": "2026-10-05T14:00:00+02:00", "energy_kwh": 3.6,
    }],
}


def test_grid_limit_keeps_room_for_fixed_devices_at_their_usual_hours(home):
    # Płyta (stała) bierze o 13:00–14:00 3,6 kW, limit 5 kW: pralka (do 2,4 kW) nie zmieści się obok niej,
    # więc idzie na tanie 14:00, a nie na 13:00.
    owner = _owner(home, WASHER, HOB)
    assert _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
    ]}).status_code == 200

    body = _create(owner, prices=_PricesWithGridLimit).json()

    washer = _items_of(body)["dev_wm_01"]
    assert washer["start"] == "2026-10-12T14:00:00+02:00"
    assert any(note.startswith("Zostawiamy zapas na pozostałe urządzenia") for note in body["notes"])


def test_water_heater_heats_only_where_it_fits_next_to_rest_of_home(home):
    # Płyta (stała) bierze 3,6 kW w tanich 13:00–15:00, limit 5 kW: bojler (2 kW) się tam nie mieści,
    # więc grzeje w innych tanich godzinach (02:00–04:00), a nie razem z płytą (5,6 kW).
    hob = {**HOB, "actions": [{
        "action_id": "act_hob_1", "device_id": "dev_hob_01",
        "action_start": "2026-10-05T13:00:00+02:00", "action_end": "2026-10-05T15:00:00+02:00", "energy_kwh": 7.2,
    }]}
    owner = _owner(home, WATER_HEATER, hob)

    body = _create(owner, prices=_PricesWithGridLimit).json()

    heater = _items_of(body)["dev_wh_01"]
    afternoon = datetime(2026, 10, 12, 13, tzinfo=WARSAW), datetime(2026, 10, 12, 15, tzinfo=WARSAW)
    assert heater["charging"]
    assert not any(
        _local(period["start"]) < afternoon[1] and _local(period["end"]) > afternoon[0] for period in heater["charging"]
    )
    assert body["water_heaters"][0]["shortfall"] == 0
    # Dało się ominąć płytę, więc nie ma ostrzeżenia o przekroczeniu.
    assert not any("mimo ryzyka przekroczenia" in warning for warning in body["warnings"])


def test_water_heater_keeps_water_hot_over_grid_limit_when_it_cannot_fit_anywhere(home):
    # Płyta bierze 3,5 kW przez całą dobę, limit 5 kW: bojler (2 kW) nie mieści się w żadnym kwadransie.
    # Ciepła woda jest ważniejsza niż limit, więc bojler grzeje, a plan mówi, kiedy grozi przekroczenie.
    hob = {**HOB, "actions": [{
        "action_id": "act_hob_1", "device_id": "dev_hob_01",
        "action_start": "2026-10-05T00:00:00+02:00", "action_end": "2026-10-06T00:00:00+02:00", "energy_kwh": 84.0,
    }]}
    owner = _owner(home, WATER_HEATER, hob)

    body = _create(owner, prices=_PricesWithGridLimit).json()

    water = body["water_heaters"][0]
    assert water["shortfall"] == 0
    temps = {_local(point["start"]).strftime("%H:%M"): point["after"] for point in water["temperatures"]}
    assert temps["05:45"] >= 55 and temps["17:45"] >= 55
    over = [warning for warning in body["warnings"] if "mimo ryzyka przekroczenia mocy przyłącza (5,0 kW)" in warning]
    assert len(over) == 1 and over[0].startswith("Bojler: grzeje o ")
    assert not any("większy zbiornik" in warning for warning in body["warnings"])


def test_grid_limit_keeps_room_for_unticked_heat_pump_running_on_its_own(home):
    # Pompa grzeje zwykle 13:00–14:00 z mocą 2,9 kW. Odznaczona nie jest w planie, ale dalej grzeje,
    # więc pralka (do 2,4 kW) przy limicie 5 kW nie zmieści się obok niej i idzie na tanie 14:00.
    heat_pump = {**HEAT_PUMP, "actions": [{
        "action_id": "act_hp_1", "device_id": "dev_hp_01",
        "action_start": "2026-10-05T13:00:00+02:00", "action_end": "2026-10-05T14:00:00+02:00", "energy_kwh": 2.9,
    }]}
    owner = _owner(home, WASHER, heat_pump)
    assert _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("07:00", "22:00"))},
        {"device_id": "dev_hp_01", "enabled": False},
    ]}).status_code == 200

    body = _create(owner, prices=_PricesWithGridLimit).json()

    assert _items_of(body)["dev_wm_01"]["start"] == "2026-10-12T14:00:00+02:00"
    assert "dev_hp_01#1" not in _items_of(body)
    assert any(note.startswith("Zapas obejmuje też: Pompa ciepła.") for note in body["notes"])


def _items_of(body) -> dict:
    return {item["action_id"]: item for item in body["items"]}


def test_plan_saved_before_newer_fields_still_reads(home, db):
    from app.models.DayPlan import DayPlan

    owner = _owner(home, WATER_HEATER)
    plan_id = _create(owner).json()["id"]
    plan = db.get(DayPlan, plan_id)
    # Plan zapisany wcześniejszą wersją: bojler bez temperatur o północy.
    old = dict(plan.result)
    old["water_heaters"] = [
        {key: value for key, value in heater.items() if key not in ("start_before", "start_after")}
        for heater in old["water_heaters"]
    ]
    plan.result = old
    db.commit()

    current = client.get("/api/v1/planning/plans/current", headers=_headers(owner))

    assert current.status_code == 200
    assert current.json()["water_heaters"][0]["start_after"] is None


def test_same_file_uploaded_twice_counts_heat_pump_history_once(home):
    owner = _owner(home, HEAT_PUMP)
    assert _upload(owner, _devices_file(HEAT_PUMP)).status_code == 200

    body = _create(owner).json()

    # Blok 12:00–13:00 (1,5 kWh) jest w obu plikach, ale starszy plik jest zastąpiony nowszym.
    assert [item["action_id"] for item in body["items"]] == ["dev_hp_01#1"]
    assert body["items"][0]["energy_kwh"] == 1.5



def _dishwasher_with_history(*starts):
    """Zmywarka (19:00–07:00, program 45 min) włączana w historii o podanych godzinach (ISO)."""
    actions = [
        {"action_id": f"act_dw_{index}", "device_id": "dev_dw_01", "program_id": "eco", "action_start": start,
         "action_end": (datetime.fromisoformat(start) + SLOT * 3).isoformat(), "energy_kwh": 0.6}
        for index, start in enumerate(starts)
    ]
    return {**DISHWASHER, "actions": actions}


def test_without_plan_devices_start_as_usual_from_history_also_after_midnight(home):
    # Zmywarka zwykle o 21:00, 23:00 i 00:30 (godzina zegarowa): mediana po przejściu przez północ to 23:00,
    # a nie 21:00, jak wyszłoby z samych godzin 00:30, 21:00, 23:00.
    dishwasher = _dishwasher_with_history(
        "2026-10-05T00:30:00+02:00", "2026-10-05T21:00:00+02:00", "2026-10-05T23:00:00+02:00",
    )
    owner = _owner(home, dishwasher)
    assert _put(owner, {"devices": [
        {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": _windows(("19:00", "07:00"))},
    ]}).status_code == 200

    body = _create(owner).json()

    assert _items_of(body)["dev_dw_01"]["original_start"] == "2026-10-12T23:00:00+02:00"
    assert "Bez planu: Zmywarka startuje o godzinie, o której zwykle jest włączane (z historii)." in body["notes"]


def test_without_plan_start_before_daytime_window_stays_that_morning(home):
    # Pralka z przedziałem 12:00–22:00 (bez przejścia przez północ) włączana o 08:00, 09:00 i 13:00:
    # mediana to 09:00, więc bez planu startuje na początku przedziału (12:00), a nie wieczorem,
    # jak wtedy, gdy 08:00 i 09:00 były liczone jako następny dzień (mediana 32:00, czyli koniec przedziału).
    actions = [
        {"action_id": f"act_wm_{index}", "device_id": "dev_wm_01", "program_id": "cotton_60", "action_start": start,
         "action_end": (datetime.fromisoformat(start) + SLOT * 3).isoformat(), "energy_kwh": 1.4}
        for index, start in enumerate((
            "2026-10-05T08:00:00+02:00", "2026-10-05T09:00:00+02:00", "2026-10-05T13:00:00+02:00",
        ))
    ]
    owner = _owner(home, {**WASHER, "actions": actions})
    assert _put(owner, {"devices": [
        {"device_id": "dev_wm_01", "enabled": True, "program_id": "cotton_60", "windows": _windows(("12:00", "22:00"))},
    ]}).status_code == 200

    body = _create(owner).json()

    assert _items_of(body)["dev_wm_01"]["original_start"] == "2026-10-12T12:00:00+02:00"


def test_without_history_device_starts_at_window_start(home):
    owner = _owner(home, {**DISHWASHER, "actions": []})
    assert _put(owner, {"devices": [
        {"device_id": "dev_dw_01", "enabled": True, "program_id": "eco", "windows": _windows(("19:00", "07:00"))},
    ]}).status_code == 200

    body = _create(owner).json()

    assert _items_of(body)["dev_dw_01"]["original_start"] == "2026-10-12T19:00:00+02:00"
    assert any("na początku podanych godzin" in note for note in body["notes"])

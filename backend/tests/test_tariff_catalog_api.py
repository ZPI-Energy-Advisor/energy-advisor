from datetime import date
from pathlib import Path

import pytest

from app.models.NewModels import RegulatoryPeriod, TariffDefinition, UnsupportedTariff
from app.schemas.other import DistributionOperatorEnum
from app.tariff_data.db import load_data_set
from app.tariff_data.files import read_data_set


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tariffs" / "valid" / "2030"
YEAR_START, YEAR_END = date(2031, 1, 1), date(2031, 12, 31)


def _delete_test_year(session) -> None:
    session.query(TariffDefinition).filter(
        TariffDefinition.osd_operator == DistributionOperatorEnum.PGE,
        TariffDefinition.valid_from >= YEAR_START,
        TariffDefinition.valid_from <= YEAR_END,
    ).delete(synchronize_session=False)
    session.query(UnsupportedTariff).filter(
        UnsupportedTariff.osd_operator == DistributionOperatorEnum.PGE,
        UnsupportedTariff.valid_from >= YEAR_START,
        UnsupportedTariff.valid_from <= YEAR_END,
    ).delete(synchronize_session=False)
    session.query(RegulatoryPeriod).filter(
        RegulatoryPeriod.valid_from >= YEAR_START, RegulatoryPeriod.valid_from <= YEAR_END
    ).delete(synchronize_session=False)
    session.commit()


@pytest.fixture
def pge_rates(db, tmp_path):
    """Zmyślony cennik PGE przesunięty na rok 2031 (rok 2030 używa inny plik testów), zatwierdzony w bazie."""
    for name in ("pge.json", "regulatory.json"):
        text = (FIXTURE_DIR / name).read_text(encoding="utf-8").replace("2030", "2031")
        (tmp_path / name).write_text(text, encoding="utf-8")
    _delete_test_year(db)
    load_data_set(db, read_data_set([tmp_path]))
    db.commit()
    yield
    db.rollback()
    _delete_test_year(db)


def profile_payload(operator="PGE", tariff_type="G12", billing_cycle=2):
    return {
        "base_info": {
            "type_of_property": "apartment",
            "year_of_construction": 2000,
            "heating_area_m2": 60,
            "number_of_residents": 2,
            "town": "Wrocław",
            "postal_code": "50-370",
            "distribution_operator": operator,
            "phase_type": "1_phase",
            "contracted_power_kw": 5,
            "billing_cycle": billing_cycle,
            "billing_period_start_date": "2031-01-01",
        },
        "consumption_and_tariff": {"tariff_type": tariff_type},
        "pv_config": {"mode": "none"},
    }


def _catalog(client, on_date="2031-03-01", operator="PGE"):
    response = client.get("/api/v1/tariffs/catalog", params={"operator": operator, "date": on_date})
    assert response.status_code == 200
    return response.json()


def test_catalog_lists_tariffs_valid_on_date(client_a, pge_rates):
    data = _catalog(client_a)

    assert data["operator"] == "PGE"
    assert data["date"] == "2031-03-01"
    assert [(tariff["code"], tariff["distribution_group"]) for tariff in data["tariffs"]] == [
        ("G11", "G11"), ("G12", "G12"), ("G12w", "G12w"), ("dynamic", "G11"), ("dynamic", "G12"),
    ]
    g12 = next(tariff for tariff in data["tariffs"] if tariff["code"] == "G12")
    assert g12["valid_from"] == "2031-01-01"
    assert g12["valid_to"] == "2031-06-30"
    assert g12["dynamic"] is None


def test_catalog_returns_rates_and_sources(client_a, pge_rates):
    g12 = next(tariff for tariff in _catalog(client_a)["tariffs"] if tariff["code"] == "G12")

    distribution = g12["distribution"]
    assert distribution["fixed_monthly_1phase"] == 8.0
    assert distribution["fixed_monthly_3phase"] == 14.0
    assert distribution["subscription"] == [
        {"billing_cycle_months": 1, "monthly_fee": 4.0},
        {"billing_cycle_months": 2, "monthly_fee": 2.0},
        {"billing_cycle_months": 6, "monthly_fee": 1.0},
    ]
    assert "s. 3" in distribution["source"]
    assert g12["energy"]["seller"] == "Sprzedawca testowy S.A."
    assert g12["energy"]["includes_excise"] is False
    assert g12["energy"]["price_cap_per_kwh"] == 0.5
    assert "s. 2" in g12["energy"]["source"]
    assert [
        (zone["zone_index"], zone["name"], zone["energy_price_per_kwh"], zone["network_rate_per_kwh"])
        for zone in g12["zones"]
    ] == [(1, "dzienna", 0.7, 0.4), (2, "nocna", 0.4, 0.1)]
    assert g12["energy"]["trade_fee_monthly"] is None


def test_catalog_returns_zone_hours_as_clock_times(client_a, pge_rates):
    g12 = next(tariff for tariff in _catalog(client_a)["tariffs"] if tariff["code"] == "G12")
    night = next(zone for zone in g12["zones"] if zone["zone_index"] == 2)

    summer = {(hour["start"], hour["end"]) for hour in night["hours"] if hour["season_from"] == "04-01"}
    winter = {(hour["start"], hour["end"]) for hour in night["hours"] if hour["season_from"] == "10-01"}
    assert summer == {("00:00", "06:00"), ("15:00", "17:00"), ("22:00", "24:00")}
    assert winter == {("00:00", "06:00"), ("13:00", "15:00"), ("22:00", "24:00")}
    assert {hour["day_type"] for hour in night["hours"]} == {"workday", "saturday", "sunday_holiday"}
    assert night["hours"][0]["season_to"] in ("09-30", "03-31")


def test_catalog_returns_dynamic_offer(client_a, pge_rates):
    dynamic = next(tariff for tariff in _catalog(client_a)["tariffs"] if tariff["code"] == "dynamic")

    assert dynamic["name"] == "Oferta dynamiczna testowa"
    assert dynamic["valid_from"] == "2031-03-01"
    assert dynamic["dynamic"] == {
        "margin": 0.08,
        "prosumer_margin": 0.11,
        "market_price_floor_mwh": 0.0,
        "market_price_cap_mwh": 2000.0,
        "billing_cycle_months": 1,
    }
    assert (dynamic["energy"]["trade_fee_monthly"], dynamic["energy"]["prosumer_trade_fee_monthly"]) == (20.0, 25.0)


def test_catalog_splits_periods_and_keeps_sources(client_a, pge_rates):
    data = _catalog(client_a, "2031-08-01")

    g12 = next(tariff for tariff in data["tariffs"] if tariff["code"] == "G12")
    assert g12["valid_from"] == "2031-07-01"
    assert g12["distribution"]["valid_from"] == "2031-07-01"
    assert "abonament" in g12["distribution"]["source"]
    assert g12["energy"]["price_cap_per_kwh"] == 0.5


def test_catalog_returns_regulatory_period_and_unsupported(client_a, pge_rates):
    data = _catalog(client_a)

    regulatory = data["regulatory"]
    assert regulatory["valid_from"] == "2031-01-01"
    assert regulatory["valid_to"] == "2031-06-30"
    assert regulatory["quality_fee_per_kwh"] == 0.03
    assert regulatory["renewable_fee_per_kwh"] == 0.004
    assert regulatory["cogeneration_fee_per_kwh"] == 0.003
    assert regulatory["excise_per_kwh"] == 0.005
    assert regulatory["vat_rate"] == 0.23
    assert regulatory["capacity_fee_monthly"][-1] == {"min_kwh": 2800.0, "max_kwh": None, "fee": 0.0}
    assert regulatory["transition_fee_monthly"] == [
        {"min_kwh": 0.0, "max_kwh": 500.0, "fee": 0.02},
        {"min_kwh": 500.0, "max_kwh": 1200.0, "fee": 0.1},
        {"min_kwh": 1200.0, "max_kwh": None, "fee": 0.33},
    ]
    assert "s. 1" in regulatory["source"]
    assert [(row["code"], row["name"]) for row in data["unsupported"]] == [("G12as", "Taryfa antysmogowa")]
    assert "dane testowe" in data["unsupported"][0]["reason"]
    assert data["unsupported"][0]["source"]


def test_catalog_for_date_without_data_is_empty(client_a, pge_rates):
    data = _catalog(client_a, "2031-01-01", operator="STOEN")
    assert data["tariffs"] == []
    assert data["unsupported"] == []
    assert data["regulatory"] is not None

    empty = _catalog(client_a, "2090-01-01")
    assert empty["tariffs"] == []
    assert empty["regulatory"] is None
    assert empty["unsupported"] == []


def test_catalog_defaults_to_today(client_a, pge_rates):
    response = client_a.get("/api/v1/tariffs/catalog", params={"operator": "PGE"})

    assert response.status_code == 200
    # Dzień w Europe/Warsaw może się różnić od lokalnego o dobę tylko tuż przy północy.
    assert abs((date.fromisoformat(response.json()["date"]) - date.today()).days) <= 1


def test_catalog_requires_operator(client_a):
    assert client_a.get("/api/v1/tariffs/catalog").status_code == 422


def test_options_list_tariffs_and_cycles(client_a, pge_rates):
    response = client_a.get("/api/v1/tariffs/options", params={"operator": "PGE"})

    assert response.status_code == 200
    data = response.json()
    assert data["has_rates"] is True
    codes = {tariff["code"]: tariff for tariff in data["tariffs"]}
    assert {"G11", "G12", "G12w"} <= set(codes)
    assert "dynamic" not in codes
    assert "G13" not in codes
    assert codes["G12"]["name"] == "G12"
    assert codes["G12"]["billing_cycles"] == [1, 2, 6]
    assert codes["G12"]["available_from"] <= "2031-01-01"
    assert codes["G12"]["available_to"] >= "2031-12-31"
    offer = data["dynamic_offer"]
    assert offer["name"] == "Oferta dynamiczna testowa"
    assert offer["distribution_groups"] == ["G11", "G12"]
    assert offer["billing_cycle_months"] == 1
    assert {1, 2, 6} <= set(data["billing_cycles"])
    assert 12 not in data["billing_cycles"]
    unsupported = [row for row in data["unsupported"] if row["code"] == "G12as"]
    assert len(unsupported) == 1
    assert unsupported[0]["name"] == "Taryfa antysmogowa"


def test_options_without_rates(client_a, pge_rates, db):
    if db.query(TariffDefinition).filter(TariffDefinition.osd_operator == DistributionOperatorEnum.STOEN).count():
        pytest.skip("Baza zawiera stawki STOEN.")

    data = client_a.get("/api/v1/tariffs/options", params={"operator": "STOEN"}).json()

    assert data == {"has_rates": False, "tariffs": [], "dynamic_offer": None, "billing_cycles": [], "unsupported": []}


def test_profile_rejects_tariff_operator_does_not_compute(client_a, pge_rates):
    response = client_a.put("/api/v1/users/me/profile", json=profile_payload(tariff_type="G13"))

    assert response.status_code == 422
    assert "G13" in response.json()["detail"]
    assert "G12w" in response.json()["detail"]


def test_profile_rejects_billing_cycle_operator_does_not_offer(client_a, pge_rates):
    response = client_a.put("/api/v1/users/me/profile", json=profile_payload(billing_cycle=12))

    assert response.status_code == 422
    assert "12" in response.json()["detail"]
    assert "1, 2, 6" in response.json()["detail"]


def test_profile_accepts_offered_tariff_and_cycle(client_a, pge_rates):
    response = client_a.put("/api/v1/users/me/profile", json=profile_payload(tariff_type="G12w", billing_cycle=2))

    assert response.status_code == 200
    assert response.json()["consumption_and_tariff"]["tariff_type"] == "G12w"


def test_profile_for_operator_without_rates_is_never_blocked(client_a, pge_rates, db):
    if db.query(TariffDefinition).filter(TariffDefinition.osd_operator == DistributionOperatorEnum.STOEN).count():
        pytest.skip("Baza zawiera stawki STOEN.")

    response = client_a.put("/api/v1/users/me/profile", json=profile_payload("STOEN", "G13", 12))

    assert response.status_code == 200


def test_profile_accepts_dynamic_price_only_with_group_allowed_by_offer(client_a, pge_rates):
    allowed = profile_payload(tariff_type="G12")
    allowed["consumption_and_tariff"]["dynamic_price"] = True
    not_allowed = profile_payload(tariff_type="G12w")
    not_allowed["consumption_and_tariff"]["dynamic_price"] = True

    assert client_a.put("/api/v1/users/me/profile", json=allowed).status_code == 200
    response = client_a.put("/api/v1/users/me/profile", json=not_allowed)
    assert response.status_code == 422
    assert "Dostępne grupy: G11, G12" in response.json()["detail"]

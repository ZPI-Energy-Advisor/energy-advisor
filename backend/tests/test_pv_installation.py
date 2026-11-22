import importlib.util

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text

from app.models.UserProfile import UserProfile as UserProfileRow
from app.schemas.user_profile import PVConfig, TYPICAL_PV_INSTALLATION, UserProfile, pv_installation
from conftest import BACKEND_DIR
from test_users_api import profile_payload, rates  # noqa: F401

MIGRATION = BACKEND_DIR / "alembic" / "versions" / "a7d3e9c2b5f1_instalacja_pv_w_profilu.py"
PV = TypeAdapter(PVConfig)


def _migration():
    spec = importlib.util.spec_from_file_location("pv_installation_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def installation(*arrays, **extra):
    return {"arrays": list(arrays), **extra}


def test_old_net_metering_power_becomes_one_south_array_with_same_discount():
    for power, k in ((6.5, 0.8), (10.0, 0.8), (12.0, 0.7)):
        pv = PV.validate_python({"mode": "net_metering", "power_of_pv_kwp": power})

        assert [(a.power_kwp, a.azimuth, a.tilt) for a in pv.installation.arrays] == [(power, 0, 35)]
        assert (pv.power_of_pv_kwp, pv.effective_k_factor) == (power, k)


def test_discount_depends_on_total_power_of_all_arrays():
    pv = PV.validate_python(
        {
            "mode": "net_metering",
            "installation": installation({"power_kwp": 6, "azimuth": -90}, {"power_kwp": 5, "azimuth": 90}),
        }
    )

    assert (pv.power_of_pv_kwp, pv.effective_k_factor) == (11.0, 0.7)


def test_saved_net_metering_reads_back_from_its_own_json():
    pv = PV.validate_python({"mode": "net_metering", "installation": installation({"power_kwp": 4.3})})

    assert PV.validate_python(PV.dump_python(pv, mode="json")) == pv


def test_panels_by_count_give_power_of_each_array():
    pv = PV.validate_python(
        {
            "mode": "net_billing",
            "installation": installation(
                {"power_kwp": 1, "panel_count": 8, "azimuth": 0},
                {"panel_count": 6, "azimuth": -90, "tilt": 30},
                panel_power_w=430,
            ),
        }
    )

    assert [a.power_kwp for a in pv.installation.arrays] == [3.44, 2.58]
    assert pv.installation.total_kwp == 6.02


def test_net_billing_without_panels_uses_typical_installation():
    pv = PV.validate_python({"mode": "net_billing", "type_of_price": "RCE"})

    assert pv.installation is None
    assert pv_installation(pv) == TYPICAL_PV_INSTALLATION
    assert TYPICAL_PV_INSTALLATION.estimated is True
    assert pv_installation(PV.validate_python({"mode": "none"})) is None


@pytest.mark.parametrize(
    "pv_installation_data",
    [
        installation({"power_kwp": 0}),
        installation({"power_kwp": 50.5}),
        installation({"power_kwp": 30}, {"power_kwp": 21}),
        installation({"power_kwp": 5, "tilt": 91}),
        installation({"power_kwp": 5, "tilt": -1}),
        installation({"power_kwp": 5, "azimuth": 181}),
        installation(),
        installation(*[{"power_kwp": 1}] * 5),
        installation({"power_kwp": 5}, panel_power_w=430),
        installation({"power_kwp": 5}, inverter_power_kw=0),
        installation({"azimuth": 0}),
        installation({"power_kwp": 5, "tilt": True}),
        installation({"power_kwp": 5, "tilt": "35"}),
        installation({"power_kwp": "5"}),
        installation({"power_kwp": 5, "azimuth": 45.5}),
        installation({"power_kwp": 5}, estimated="yes"),
        installation({"panel_count": 4}, panel_power_w=430.5),
        installation({"panel_count": 0}, panel_power_w=430),
    ],
)
def test_invalid_installation_is_rejected(pv_installation_data):
    with pytest.raises(ValidationError):
        PV.validate_python({"mode": "net_billing", "installation": pv_installation_data})


def test_net_metering_requires_power():
    with pytest.raises(ValidationError):
        PV.validate_python({"mode": "net_metering"})


@pytest.mark.usefixtures("rates")
def test_profile_api_rejects_installation_with_message_for_the_form(client_a):
    payload = profile_payload()
    payload["pv_config"] = {"mode": "net_billing", "installation": installation({"power_kwp": 30}, {"power_kwp": 25})}

    response = client_a.put("/api/v1/users/me/profile", json=payload)

    assert response.status_code == 422
    assert "50 kWp" in response.json()["detail"][0]["msg"]


@pytest.mark.usefixtures("rates")
def test_profile_api_saves_and_returns_installation(client_a):
    payload = profile_payload()
    payload["pv_config"] = {
        "mode": "net_billing",
        "type_of_price": "RCE",
        "installation": installation(
            {"panel_count": 4, "azimuth": 0, "tilt": 35},
            {"panel_count": 3, "azimuth": -90, "tilt": 35},
            panel_power_w=450,
            inverter_power_kw=3,
        ),
    }

    saved = client_a.put("/api/v1/users/me/profile", json=payload).json()["pv_config"]["installation"]

    assert [a["power_kwp"] for a in saved["arrays"]] == [1.8, 1.35]
    assert (saved["total_kwp"], saved["inverter_power_kw"], saved["estimated"]) == (3.15, 3.0, False)
    assert client_a.get("/api/v1/users/me/profile").json()["pv_config"]["installation"] == saved


def test_migration_moves_net_metering_power_into_installation_and_back(db, user_a):
    payload = profile_payload()
    payload["pv_config"] = {"mode": "net_metering", "power_of_pv_kwp": 12.0, "effective_k_factor": 0.7}
    db.add(UserProfileRow(user_id=user_a.id, **payload))
    db.commit()
    migration = _migration()

    db.execute(text(migration.UPGRADE_NET_METERING))
    db.commit()
    db.expire_all()
    upgraded = db.get(UserProfileRow, user_a.id)
    profile = UserProfile.model_validate(upgraded)

    assert upgraded.pv_config["installation"]["arrays"] == [
        {"power_kwp": 12.0, "azimuth": 0, "tilt": 35, "panel_count": None}
    ]
    assert (profile.pv_config.power_of_pv_kwp, profile.pv_config.effective_k_factor) == (12.0, 0.7)
    assert PV.validate_python(upgraded.pv_config).installation == profile.pv_config.installation

    for statement in migration.DOWNGRADE_STATEMENTS:
        db.execute(text(statement))
    db.commit()
    db.expire_all()

    assert db.get(UserProfileRow, user_a.id).pv_config == {
        "mode": "net_metering",
        "power_of_pv_kwp": 12.0,
        "effective_k_factor": 0.7,
    }

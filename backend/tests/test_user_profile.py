from uuid import uuid4
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.user_repository import UserRepository
from app.schemas.user_profile import UserProfile
from app.services.upload_service import UploadService


def valid_profile(**overrides):
    profile = {
        "base_info": {
            "type_of_property": "apartment",
            "year_of_construction": 2000,
            "heating_area_m2": 60,
            "number_of_residents": 2,
            "town": "Krakow",
        },
        "consumption_and_tariff": {
            "tariff_type": "G12",
            "imported_energy_per_zone_kwh": [1200, 800],
            "ure_price_per_zone_kwh": [0.8, 0.4],
        },
        "pv_config": {
            "mode": "net_metering",
            "power_of_pv_kwp": 6,
            "exported_energy_per_zone_kwh": [500, 300],
        },
        "commercial_offer": {
            "price_per_zone_kwh": [0.7, 0.35],
            "monthly_commercial_fee_pln": 10,
            "early_exit_penalty_pln": 100,
        },
        "distribution_fees": {
            "fixed_monthly_osd_fee_pln": 20,
            "variable_osd_fee_per_zone_kwh": [0.2, 0.1],
        },
    }
    profile.update(overrides)
    return UserProfile.model_validate(profile)


def test_profile_accepts_all_sections_and_serializes_enums():
    profile = valid_profile()

    data = profile.model_dump(mode="json")

    assert data["base_info"]["type_of_property"] == "apartment"
    assert data["consumption_and_tariff"]["tariff_type"] == "G12"
    assert data["pv_config"]["mode"] == "net_metering"
    assert data["pv_config"]["effective_k_factor"] == 0.8


@pytest.mark.parametrize(
    ("tariff", "zone_count"),
    [("G11", 1), ("G12", 2), ("G12w", 2), ("G13", 3), ("G13s", 3), ("G14d", 4)],
)
def test_profile_requires_tariff_zone_count(tariff, zone_count):
    profile = valid_profile().model_dump()
    profile["consumption_and_tariff"] = {
        "tariff_type": tariff,
        "imported_energy_per_zone_kwh": [100] * zone_count,
        "ure_price_per_zone_kwh": [0.5] * zone_count,
    }
    profile["pv_config"] = {"mode": "none"}
    profile["commercial_offer"] = None
    profile["distribution_fees"] = {"fixed_monthly_osd_fee_pln": 0}

    assert UserProfile.model_validate(profile).consumption_and_tariff.tariff_type.value == tariff


@pytest.mark.parametrize(
    "section",
    ["imported_energy_per_zone_kwh", "ure_price_per_zone_kwh"],
)
def test_profile_rejects_wrong_consumption_zone_count(section):
    profile = valid_profile().model_dump()
    profile["consumption_and_tariff"][section] = [1]

    with pytest.raises(ValidationError, match="wymaga dokładnie"):
        UserProfile.model_validate(profile)


def test_profile_rejects_wrong_dependent_zone_counts():
    profile = valid_profile().model_dump()
    profile["pv_config"]["exported_energy_per_zone_kwh"] = [100]

    with pytest.raises(ValidationError, match="eksport energii"):
        UserProfile.model_validate(profile)


@pytest.mark.parametrize(
    ("mode", "data"),
    [
        (
            "net_billing",
            {
                "mode": "net_billing",
                "exported_energy_total_kwh": 1000,
                "estimated_buyback_price_per_kwh": 0.3,
            },
        ),
        ("none", {"mode": "none"}),
    ],
)
def test_profile_supports_pv_modes(mode, data):
    profile = valid_profile().model_dump()
    profile["pv_config"] = data
    profile["commercial_offer"] = None
    profile["distribution_fees"] = {"fixed_monthly_osd_fee_pln": 0}

    assert UserProfile.model_validate(profile).pv_config.mode == mode


def test_profile_rejects_invalid_pv_discriminator():
    profile = valid_profile().model_dump()
    profile["pv_config"] = {"mode": "unsupported"}

    with pytest.raises(ValidationError):
        UserProfile.model_validate(profile)


def test_repository_create_profile_serializes_jsonb_values():
    db = MagicMock()
    repository = UserRepository(db)
    user_id = uuid4()
    profile_data = valid_profile()

    created = repository.create_profile(user_id, profile_data)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(created)
    assert created.user_id == user_id
    assert created.base_info["type_of_property"] == "apartment"
    assert created.consumption_and_tariff["tariff_type"] == "G12"


def test_repository_update_profile_updates_every_jsonb_section():
    db = MagicMock()
    repository = UserRepository(db)
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing
    profile_data = valid_profile()

    updated = repository.update_profile(uuid4(), profile_data)

    assert updated is existing
    assert existing.base_info["town"] == "Krakow"
    assert existing.pv_config["mode"] == "net_metering"
    assert existing.commercial_offer["monthly_commercial_fee_pln"] == 10
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(existing)


def _service(user_repository):
    return UploadService(
        calculation_service=MagicMock(),
        simulation_repository=MagicMock(),
        energy_file_repository=MagicMock(),
        user_repository=user_repository,
    )


def test_service_creates_profile_when_it_does_not_exist():
    repository = MagicMock()
    profile_data = valid_profile()
    stored = MagicMock(
        user_id=uuid4(),
        **profile_data.model_dump(mode="json"),
    )
    repository.get_profile.return_value = None
    repository.create_profile.return_value = stored

    result = _service(repository).create_or_update_user_profile(uuid4(), profile_data)

    repository.create_profile.assert_called_once()
    repository.update_profile.assert_not_called()
    assert result == profile_data


def test_service_updates_profile_when_it_exists():
    repository = MagicMock()
    profile_data = valid_profile()
    stored = MagicMock(
        user_id=uuid4(),
        **profile_data.model_dump(mode="json"),
    )
    repository.get_profile.return_value = stored
    repository.update_profile.return_value = stored

    result = _service(repository).create_or_update_user_profile(uuid4(), profile_data)

    repository.update_profile.assert_called_once()
    repository.create_profile.assert_not_called()
    assert result == profile_data


def test_service_get_profile_returns_404_when_missing():
    repository = MagicMock()
    repository.get_profile.return_value = None

    with pytest.raises(HTTPException) as error:
        _service(repository).get_user_profile(uuid4())

    assert error.value.status_code == 404


def test_service_get_profile_returns_409_for_incomplete_record():
    repository = MagicMock()
    repository.get_profile.return_value = MagicMock(
        base_info=None,
        consumption_and_tariff=None,
        pv_config=None,
        commercial_offer=None,
        distribution_fees=None,
    )

    with pytest.raises(HTTPException) as error:
        _service(repository).get_user_profile(uuid4())

    assert error.value.status_code == 409

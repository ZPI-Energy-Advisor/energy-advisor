from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.repositories.user_repository import UserRepository
from app.schemas.user_profile import UserProfile
from app.services.upload_service import UploadService


def valid_profile(**overrides):
    profile = {
        "connection": {
            "postal_code": "30-001",
            "phase_type": "3_phase",
            "billing_cycle": 2,
        },
        "consumption": {
            "tariff_type": "G12",
            "annual_imported_kwh_per_zone": [1200, 800],
        },
        "pv_config": {
            "mode": "net_metering",
            "power_of_pv_kwp": 6,
            "annual_exported_energy_per_zone_kwh": [500, 300],
        },
        "commercial_offer": {
            "price_per_zone_kwh": [0.7, 0.35],
            "monthly_commercial_fee_pln": 10,
            "contract_duration_months": 24,
            "early_exit_penalty_pln": 100,
        },
    }
    profile.update(overrides)
    return UserProfile.model_validate(profile)


def test_profile_accepts_all_sections_and_serializes_computed_values():
    profile = valid_profile()
    data = profile.model_dump(mode="json")

    assert data["connection"]["postal_code"] == "30-001"
    assert data["consumption"]["total_annual_kwh"] == 2000
    assert data["pv_config"]["effective_k_factor"] == 0.8


@pytest.mark.parametrize(
    ("tariff", "zone_count"),
    [("G11", 1), ("G12", 2), ("G12w", 2), ("G13", 3), ("G13s", 3), ("G14d", 4)],
)
def test_profile_requires_tariff_zone_count(tariff, zone_count):
    profile = valid_profile(
        consumption={
            "tariff_type": tariff,
            "annual_imported_kwh_per_zone": [100] * zone_count,
        },
        pv_config={"mode": "none"},
        commercial_offer=None,
    )
    assert profile.consumption.tariff_type.value == tariff


def test_profile_rejects_wrong_zone_counts():
    with pytest.raises(ValidationError, match="wymaga"):
        valid_profile(
            consumption={
                "tariff_type": "G12",
                "annual_imported_kwh_per_zone": [100],
            }
        )


def test_profile_rejects_dependent_zone_count():
    with pytest.raises(ValidationError, match="stref eksportu"):
        valid_profile(
            pv_config={
                "mode": "net_metering",
                "power_of_pv_kwp": 6,
                "annual_exported_energy_per_zone_kwh": [100],
            }
        )


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
    assert created.connection["postal_code"] == "30-001"
    assert created.consumption["tariff_type"] == "G12"


def test_repository_update_profile_updates_every_jsonb_section():
    db = MagicMock()
    repository = UserRepository(db)
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    updated = repository.update_profile(uuid4(), valid_profile())

    assert updated is existing
    assert existing.connection["postal_code"] == "30-001"
    assert existing.pv_config["mode"] == "net_metering"
    assert existing.commercial_offer["contract_duration_months"] == 24
    db.commit.assert_called_once()


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
    stored = MagicMock(user_id=uuid4(), **profile_data.model_dump(mode="json"))
    repository.get_profile.return_value = None
    repository.create_profile.return_value = stored

    result = _service(repository).create_or_update_user_profile(uuid4(), profile_data)

    repository.create_profile.assert_called_once()
    assert result == profile_data


def test_service_get_profile_returns_404_when_missing():
    repository = MagicMock()
    repository.get_profile.return_value = None

    with pytest.raises(HTTPException) as error:
        _service(repository).get_user_profile(uuid4())

    assert error.value.status_code == 404

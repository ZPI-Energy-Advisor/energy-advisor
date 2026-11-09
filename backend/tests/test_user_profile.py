from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.repositories.user_repository import UserRepository
from app.schemas.other import BillingCycleEnum, TariffTypeEnum
from app.schemas.user_profile import UserProfile
from app.services.user_service import UserService


def valid_profile(**overrides):
    profile = {
        "base_info": {
            "type_of_property": "single_family_house",
            "year_of_construction": 2000,
            "heating_area_m2": 120,
            "number_of_residents": 3,
            "town": "Krakow",
            "postal_code": "30-001",
            "distribution_operator": "PGE Dystrybucja",
            "phase_type": "3_phase",
            "contracted_power_kw": 12,
            "billing_cycle": 2,
            "billing_period_start_date": "2026-01-01",
        },
        "consumption_and_tariff": {
            "tariff_type": "G12",
        },
        "pv_config": {
            "mode": "net_metering",
            "power_of_pv_kwp": 6,
        },
    }
    profile.update(overrides)
    return UserProfile.model_validate(profile)


def test_profile_accepts_all_sections_and_serializes_computed_values():
    profile = valid_profile()
    data = profile.model_dump(mode="json")

    assert data["base_info"]["postal_code"] == "30-001"
    assert data["consumption_and_tariff"]["tariff_type"] == "G12"
    assert data["pv_config"]["effective_k_factor"] == 0.8
    assert "custom_k_factor" not in data["pv_config"]


@pytest.mark.parametrize(
    "tariff",
    ["G11", "G12", "G12w", "G13", "G13s", "G14d"],
)
def test_profile_accepts_tariff_without_zone_consumption(tariff):
    profile = valid_profile(
        consumption_and_tariff={
            "tariff_type": tariff,
        },
        pv_config={"mode": "none"},
    )
    assert profile.consumption_and_tariff.tariff_type.value == tariff


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
    assert created.base_info["postal_code"] == "30-001"
    assert created.consumption_and_tariff["tariff_type"] == "G12"


def test_repository_update_profile_updates_every_jsonb_section():
    db = MagicMock()
    repository = UserRepository(db)
    existing = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    updated = repository.update_profile(uuid4(), valid_profile())

    assert updated is existing
    assert existing.base_info["postal_code"] == "30-001"
    assert existing.pv_config["mode"] == "net_metering"
    assert existing.consumption_and_tariff["tariff_type"] == "G12"
    db.commit.assert_called_once()


def _service(user_repository):
    return UserService(user_repository, MagicMock())


def test_service_creates_profile_when_it_does_not_exist():
    repository = MagicMock()
    profile_data = valid_profile()
    stored = MagicMock(user_id=uuid4(), **profile_data.model_dump(mode="json"))
    repository.get_profile.return_value = None
    repository.create_profile.return_value = stored

    result = _service(repository).save_profile(MagicMock(id=uuid4()), profile_data)

    repository.create_profile.assert_called_once()
    assert result == profile_data


def _definition(code, cycles=(1, 2, 6)):
    return MagicMock(
        tariff_code=TariffTypeEnum(code),
        subscription_fees=[MagicMock(billing_cycle_months=cycle) for cycle in cycles],
    )


def _service_with_rates(definitions):
    repository = MagicMock()
    repository.get_profile.return_value = None
    definition_repository = MagicMock()
    definition_repository.list_for_operator.return_value = definitions
    return UserService(repository, MagicMock(), definition_repository), repository


def test_service_rejects_tariff_missing_in_rates():
    service, repository = _service_with_rates([_definition("G11"), _definition("G12")])

    with pytest.raises(HTTPException) as error:
        service.save_profile(MagicMock(id=uuid4()), valid_profile(consumption_and_tariff={"tariff_type": "G13"}))

    assert error.value.status_code == 422
    assert "G13" in error.value.detail
    assert "G11, G12" in error.value.detail
    repository.create_profile.assert_not_called()


def test_service_rejects_billing_cycle_missing_in_rates():
    service, repository = _service_with_rates([_definition("G12")])
    profile = valid_profile()
    profile.base_info.billing_cycle = BillingCycleEnum.TWELVE_MONTHS

    with pytest.raises(HTTPException) as error:
        service.save_profile(MagicMock(id=uuid4()), profile)

    assert error.value.status_code == 422
    assert "12" in error.value.detail
    repository.create_profile.assert_not_called()


def test_service_saves_profile_for_operator_without_rates():
    service, repository = _service_with_rates([])
    profile_data = valid_profile(consumption_and_tariff={"tariff_type": "G13"})
    repository.create_profile.return_value = MagicMock(user_id=uuid4(), **profile_data.model_dump(mode="json"))

    service.save_profile(MagicMock(id=uuid4()), profile_data)

    repository.create_profile.assert_called_once()


def test_service_get_profile_returns_404_when_missing():
    repository = MagicMock()
    repository.get_profile.return_value = None

    with pytest.raises(HTTPException) as error:
        _service(repository).get_profile(MagicMock(id=uuid4()))

    assert error.value.status_code == 404


def test_legacy_dynamic_tariff_becomes_g11_with_dynamic_price():
    profile = valid_profile(consumption_and_tariff={"tariff_type": "dynamic"}, pv_config={"mode": "none"})

    assert profile.consumption_and_tariff.tariff_type.value == "G11"
    assert profile.consumption_and_tariff.dynamic_price is True


def test_dynamic_price_is_separate_from_tariff_group():
    profile = valid_profile(consumption_and_tariff={"tariff_type": "G13", "dynamic_price": True}, pv_config={"mode": "none"})

    assert (profile.consumption_and_tariff.tariff_type.value, profile.consumption_and_tariff.dynamic_price) == ("G13", True)


def test_net_billing_profile_keeps_rcem_choice_and_defaults_to_rce():
    chosen = valid_profile(pv_config={"mode": "net_billing", "type_of_price": "RCEm"})
    default = valid_profile(pv_config={"mode": "net_billing"})

    assert chosen.model_dump(mode="json")["pv_config"]["type_of_price"] == "RCEm"
    assert default.pv_config.type_of_price.value == "RCE"


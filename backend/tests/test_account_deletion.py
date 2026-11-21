# ruff: noqa: F811 (fikstury db i home są parametrami testów)
"""ZP-53: usunięcie konta ze wszystkimi danymi (prawo do usunięcia)."""
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.database import Base
from app.models.HomeConnection import HomeConnection
from app.models.User import User
from app.repositories.user_repository import UserRepository
from app.schemas.user_profile import UserProfile as UserProfileSchema
from app.services.home_service import RELEASE_FAILED_MESSAGE, registry_hash
from app.services.user_service import DELETE_CONFIRMATION_MESSAGE
from test_energy_files import _headers, client
from test_home import WASHER, _connect, _devices_file, _reset_home, _upload, db  # noqa: F401 (db: fixture)
from test_home_control import home  # noqa: F401 (home: fixture)
from test_home_events import _report
from test_plan_run import _home_with_files, _plan, _start, _store_events
from test_tariff_catalog_api import profile_payload


def _delete(user, email: str):
    return client.request("DELETE", "/api/v1/users/me", json={"confirm_email": email}, headers=_headers(user))


def _home_row(db) -> HomeConnection:
    db.expire_all()
    return db.get(HomeConnection, HomeConnection.SINGLE_ROW_ID)


def _row_counts(db) -> dict[str, int]:
    return {table.name: db.execute(select(func.count()).select_from(table)).scalar_one() for table in Base.metadata.sorted_tables}


def _full_account(db, home):
    """Właściciel domu ze wszystkim, co da się zapisać: profil, plik urządzeń, szablon i plan, przebieg planu
    w symulacji, zdarzenia huba i token odświeżania."""
    owner = _home_with_files(home)
    repository = UserRepository(db)
    repository.create_profile(owner.id, UserProfileSchema.model_validate(profile_payload()))
    repository.save_refresh_token(owner.id, f"hash-{owner.id}", datetime.now() + timedelta(days=7))
    assert _connect(owner).status_code == 200
    plan = _plan(owner)
    run = _start(owner, plan["id"]).json()
    _store_events(db, owner, [_report(run["simulation_id"], "dev_wm_01", plan["items"][0]["start"], 0.5)])
    return owner


def test_deleting_account_leaves_no_row_of_user_in_any_table(db, home):
    before = _row_counts(db)  # Właściciel z fikstury już jest, ale jeszcze bez danych.
    owner = _full_account(db, home)
    filled = _row_counts(db)
    # Sprawdzamy coś, co naprawdę zapisaliśmy.
    for table in ("user_profiles", "tokens", "energy_data_files", "simulations", "device_instances", "device_actions",
                  "device_slot_usage", "planning_templates", "day_plans", "plan_runs", "home_events"):
        assert filled[table] > before[table], table

    response = _delete(owner, owner.email)

    assert response.status_code == 204, response.text
    after = _row_counts(db)
    changed = {table: (before[table], after[table]) for table in before if after[table] != before[table]}
    assert changed == {"users": (before["users"], before["users"] - 1)}


def test_deleting_account_keeps_other_users_data(db, home):
    _upload(home.other, _devices_file(WASHER))
    other_files = client.get("/api/v1/energy-files", headers=_headers(home.other)).json()["total"]
    owner = _full_account(db, home)

    assert _delete(owner, owner.email).status_code == 204

    assert client.get("/api/v1/energy-files", headers=_headers(home.other)).json()["total"] == other_files == 1


def test_confirmation_must_be_the_account_email(db, home):
    owner = _home_with_files(home)

    response = _delete(owner, "ktos@example.com")

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == DELETE_CONFIRMATION_MESSAGE
    assert db.get(User, owner.id) is not None


def test_confirmation_ignores_case_and_surrounding_spaces(db, home):
    owner = _home_with_files(home)

    assert _delete(owner, f"  {owner.email.upper()} ").status_code == 204
    assert UserRepository(db).get_by_id(owner.id) is None


def test_home_owner_is_disconnected_and_hub_stops_devices(db, home):
    owner = _full_account(db, home)
    assert _home_row(db).user_id == owner.id

    assert _delete(owner, owner.email).status_code == 204

    # Hub przyjął pusty rejestr, więc zatrzymał mikroserwisy wszystkich urządzeń.
    home_row = _home_row(db)
    assert (home_row.user_id, home_row.registry_hash, home_row.sync_error) == (None, registry_hash([]), None)


def test_account_stays_when_hub_does_not_confirm_disconnection(db, home):
    owner = _full_account(db, home)
    home.hub.down = True

    response = _delete(owner, owner.email)

    assert (response.status_code, response.json()["detail"]) == (503, RELEASE_FAILED_MESSAGE)
    assert db.get(User, owner.id) is not None
    # Ponowna próba, gdy hub już odpowiada, kończy usunięcie.
    home.hub.down = False
    assert _delete(owner, owner.email).status_code == 204
    assert _home_row(db).registry_hash == registry_hash([])


def test_user_without_home_is_deleted_without_asking_hub(db, home):
    owner = _home_with_files(home)
    assert _connect(owner).status_code == 200
    synced = _home_row(db).registry_hash
    _upload(home.other, _devices_file(WASHER))

    assert _delete(home.other, home.other.email).status_code == 204

    # Dom właściciela zostaje podłączony z tym samym rejestrem.
    assert (_home_row(db).user_id, _home_row(db).registry_hash) == (owner.id, synced)


def test_deleted_account_is_logged_out(db, home):
    owner = _home_with_files(home)
    assert _delete(owner, owner.email).status_code == 204

    # Token sprzed usunięcia już nic nie otwiera.
    assert client.get("/api/v1/users/me", headers=_headers(owner)).status_code == 401
    assert client.get("/api/v1/energy-files", headers=_headers(owner)).status_code == 401


def test_owner_who_never_connected_home_is_deleted_when_hub_is_down(db, home):
    owner = home.owner
    _reset_home(db)
    assert _home_row(db).registry_hash is None
    home.hub.down = True

    assert _delete(owner, owner.email).status_code == 204
    assert UserRepository(db).get_by_id(owner.id) is None

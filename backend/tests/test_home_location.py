import httpx
import pytest

from app.models.UserProfile import UserProfile as UserProfileRow
from app.providers import geocoding
from app.providers.geocoding import GeocoderError, NominatimGeocoder, Place, distance_km
from app.schemas.user_profile import BaseInfo, HomeLocation, LocationSource
from app.services.home_location import AddressError, locate_home, lookup_address, resolve_location
from test_users_api import profile_payload, rates  # noqa: F401

WROCLAW = Place(51.1079, 17.0385, "Wrocław")

POSTAL_CODES = {
    "50-370": Place(51.107, 17.061, "Wrocław"),
    "51-515": Place(51.11, 17.143, "Wrocław"),
    "64-510": Place(52.705, 16.345, "gmina Wronki"),
    "31-001": Place(50.06, 19.94, "Kraków"),
}
TOWNS = {
    "Wrocław": [Place(51.109, 17.033, "Wrocław")],
    "Wronki": [Place(52.71, 16.374, "Wronki")],
    "Kraków": [Place(50.062, 19.937, "Kraków")],
    "Nowa Wieś": [Place(49.907, 19.216, "Nowa Wieś"), Place(53.653, 20.61, "Nowa Wieś")],
}


class FakeGeocoder:
    def __init__(self, postal=POSTAL_CODES, towns=TOWNS, error=None, reverse=None):
        self.postal = postal
        self.towns = towns
        self.reverse = reverse or {}
        self.error = error
        self.calls = []

    def by_postal_code(self, postal_code):
        self.calls.append(("postal_code", postal_code))
        if self.error:
            raise self.error
        return self.postal.get(postal_code)

    def by_town(self, town, near=None):
        self.calls.append(("town", town))
        places = next((value for key, value in self.towns.items() if key.casefold() == town.casefold()), [])
        return [place for place in places if near is None or distance_km(place, near) < 35]

    def postal_code_at(self, place):
        self.calls.append(("reverse", place.name))
        return self.reverse.get(place.name)


def base_info(town="Wrocław", postal_code="50-370", location=None, **extra):
    data = {
        "type_of_property": "single_family_house",
        "year_of_construction": 2000,
        "heating_area_m2": 120,
        "number_of_residents": 3,
        "town": town,
        "postal_code": postal_code,
        "distribution_operator": "TAURON",
        "phase_type": "3_phase",
        "contracted_power_kw": 12,
        "billing_cycle": 2,
        "billing_period_start_date": "2026-01-01",
        **extra,
    }
    if location is not ...:
        data["location"] = location
    return BaseInfo.model_validate(data)


def test_town_matching_postal_code_gives_coordinates_of_that_town():
    location = locate_home(base_info(), FakeGeocoder())

    assert location.source == LocationSource.POSTAL_CODE
    assert location.approximate is False
    assert distance_km(Place(location.latitude, location.longitude), WROCLAW) < 5
    assert (location.label, location.address) == ("Wrocław", "50-370 Wrocław")


def test_town_matching_postal_code_is_written_without_diacritics_but_shown_correctly():
    towns = {"Wroclaw": TOWNS["Wrocław"]}

    location = locate_home(base_info("Wroclaw", "51-515"), FakeGeocoder(towns=towns))

    assert location.label == "Wrocław"


def test_town_from_other_end_of_poland_does_not_match_postal_code():
    with pytest.raises(AddressError) as error:
        locate_home(base_info("Wronki", "51-515"), FakeGeocoder())

    assert error.value.errors == {"town": "Miejscowość Wronki nie pasuje do kodu pocztowego 51-515. Ten kod to okolice: Wrocław."}


def test_random_town_is_rejected_even_with_real_postal_code():
    with pytest.raises(AddressError) as error:
        locate_home(base_info("Qwzxkj", "51-515"), FakeGeocoder())

    assert set(error.value.errors) == {"town"}


def test_unknown_postal_code_and_unknown_town_are_both_marked():
    with pytest.raises(AddressError) as error:
        locate_home(base_info("Qwzxkj", "99-999"), FakeGeocoder())

    assert set(error.value.errors) == {"postal_code", "town"}


def test_postal_code_missing_in_openstreetmap_takes_town_from_its_region():
    geocoder = FakeGeocoder()

    location = locate_home(base_info("Nowa Wieś", "11-030"), geocoder)

    assert location.source == LocationSource.TOWN
    assert (location.latitude, location.longitude) == (53.653, 20.61)
    assert geocoder.calls == [("postal_code", "11-030"), ("town", "Nowa Wieś")]


def test_postal_code_missing_in_openstreetmap_must_be_in_region_of_town():
    with pytest.raises(AddressError) as error:
        locate_home(base_info("Wronki", "31-999"), FakeGeocoder())

    assert set(error.value.errors) == {"postal_code"}


def test_wrong_address_on_read_gives_approximate_location_instead_of_error():
    location = locate_home(base_info("Wronki", "51-515"), FakeGeocoder(), strict=False)

    assert (location.source, location.label) == (LocationSource.POSTAL_REGION, "Wrocław")


def test_network_error_falls_back_to_postal_region():
    location = locate_home(base_info(), FakeGeocoder(error=GeocoderError("timeout")))

    assert location.source == LocationSource.POSTAL_REGION
    assert location.label == "Wrocław"


def test_same_address_reuses_saved_location_without_geocoder():
    previous = HomeLocation(latitude=51.1, longitude=17.06, source="postal_code", address="50-370 Wrocław")
    geocoder = FakeGeocoder()

    assert resolve_location(base_info(), previous, geocoder) == previous
    assert geocoder.calls == []


def test_changed_address_is_checked_and_located_again():
    previous = HomeLocation(latitude=51.1, longitude=17.06, source="postal_code", address="50-370 Wrocław")

    location = resolve_location(base_info("Kraków", "31-001"), previous, FakeGeocoder())

    assert (location.latitude, location.longitude) == (50.062, 19.937)
    with pytest.raises(AddressError):
        resolve_location(base_info("Kraków", "51-515"), previous, FakeGeocoder())


def test_approximate_location_is_retried_on_save():
    previous = HomeLocation(latitude=51.1079, longitude=17.0385, source="postal_region", address="50-370 Wrocław")

    assert resolve_location(base_info(), previous, FakeGeocoder()).source == LocationSource.POSTAL_CODE


def test_client_cannot_set_coordinates_other_than_manual():
    sent = {"latitude": 54.35, "longitude": 18.65, "source": "postal_code", "address": "50-370 Wrocław"}

    location = resolve_location(base_info(location=sent), None, FakeGeocoder())

    assert (location.latitude, location.longitude) == (51.109, 17.033)


def test_manual_location_is_kept_until_address_changes():
    manual = {"latitude": 51.2, "longitude": 17.2, "source": "manual", "address": "50-370 Wrocław", "label": "<b>x</b>"}

    kept = resolve_location(base_info(location=manual), None, FakeGeocoder())
    moved = resolve_location(base_info("Kraków", "31-001", location=manual), kept, FakeGeocoder())

    assert (kept.source, kept.latitude, kept.label) == (LocationSource.MANUAL, 51.2, None)
    assert (moved.source, moved.latitude) == (LocationSource.POSTAL_CODE, 50.062)


def test_manual_location_does_not_skip_address_check():
    manual = {"latitude": 51.2, "longitude": 17.2, "source": "manual", "address": "51-515 Wronki"}

    with pytest.raises(AddressError):
        resolve_location(base_info("Wronki", "51-515", location=manual), None, FakeGeocoder())


def test_explicit_null_replaces_manual_location_with_located_one():
    manual = HomeLocation(latitude=51.2, longitude=17.2, source="manual", address="50-370 Wrocław")

    omitted = resolve_location(base_info(location=...), manual, FakeGeocoder())
    reset = resolve_location(base_info(location=None), manual, FakeGeocoder())

    assert omitted == manual
    assert reset.source == LocationSource.POSTAL_CODE


@pytest.mark.parametrize("latitude, longitude", [(48.5, 19.0), (52.0, 25.0), (60.0, 10.0)])
def test_location_outside_poland_is_rejected(latitude, longitude):
    with pytest.raises(ValueError):
        HomeLocation(latitude=latitude, longitude=longitude, source="manual")


def _nominatim(handler):
    return NominatimGeocoder(httpx.Client(transport=httpx.MockTransport(handler)), base_url="https://geo.test")


def test_nominatim_asks_only_in_poland_and_caches_answers(monkeypatch):
    monkeypatch.setattr("app.providers.geocoding.MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(NominatimGeocoder, "_unavailable_until", 0.0)
    requests = []

    def handler(request):
        requests.append(request)
        if "postalcode" in request.url.params:
            return httpx.Response(200, json=[{"lat": "51.11", "lon": "17.143", "name": "51-515", "address": {"city": "Wrocław"}}])
        return httpx.Response(200, json=[{"lat": "51.109", "lon": "17.033", "name": "Wrocław"}])

    geocoder = _nominatim(handler)
    area = geocoder.by_postal_code("51-515")

    assert area == geocoder.by_postal_code("51-515") == Place(51.11, 17.143, "Wrocław")
    assert geocoder.by_town("Wrocław", near=area) == [Place(51.109, 17.033, "Wrocław")]
    assert len(requests) == 2
    postal, town = (request.url.params for request in requests)
    assert (postal["postalcode"], postal["countrycodes"], postal["format"]) == ("51-515", "pl", "jsonv2")
    assert (town["city"], town["bounded"], town["countrycodes"]) == ("Wrocław", "1", "pl")
    west, north, east, south = map(float, town["viewbox"].split(","))
    assert west < 17.143 < east and south < 51.11 < north


def test_nominatim_reads_postal_code_at_point(monkeypatch):
    monkeypatch.setattr("app.providers.geocoding.MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(NominatimGeocoder, "_unavailable_until", 0.0)
    answers = {"50.9": {"address": {"postcode": "55-050"}}, "51.0": {"error": "Unable to geocode"}}
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=answers[request.url.params["lat"]])

    geocoder = _nominatim(handler)

    assert geocoder.postal_code_at(Place(50.9, 16.7)) == geocoder.postal_code_at(Place(50.9, 16.7)) == "55-050"
    assert geocoder.postal_code_at(Place(51.0, 16.7)) is None
    assert len(requests) == 2 and requests[0].url.path == "/reverse"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(429), httpx.Response(503), httpx.Response(200, text="<html>"), httpx.Response(200, json={"error": 1})],
)
def test_nominatim_errors_are_geocoder_errors(monkeypatch, response):
    monkeypatch.setattr("app.providers.geocoding.MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(NominatimGeocoder, "_unavailable_until", 0.0)

    with pytest.raises(GeocoderError):
        _nominatim(lambda request: response).by_postal_code("50-370")


def test_town_with_spaces_only_is_rejected_and_town_is_trimmed():
    with pytest.raises(ValueError):
        base_info("   ")

    assert base_info("  Wrocław ").address_key() == "50-370 Wrocław"


def test_long_place_name_does_not_break_location():
    geocoder = FakeGeocoder(towns={"Wrocław": [Place(51.1, 17.03, "W" * 300)]})

    location = locate_home(base_info(), geocoder)

    assert (location.source, len(location.label)) == (LocationSource.POSTAL_CODE, 200)


def test_unavailable_nominatim_is_not_asked_again_for_a_while(monkeypatch):
    monkeypatch.setattr("app.providers.geocoding.MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(NominatimGeocoder, "_unavailable_until", 0.0)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503)

    geocoder = _nominatim(handler)
    for _ in range(3):
        with pytest.raises(GeocoderError):
            geocoder.by_postal_code("50-370")

    assert len(requests) == 1
    assert locate_home(base_info(), geocoder).source == LocationSource.POSTAL_REGION


def test_not_found_does_not_pause_nominatim(monkeypatch):
    monkeypatch.setattr("app.providers.geocoding.MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(NominatimGeocoder, "_unavailable_until", 0.0)
    geocoder = _nominatim(lambda request: httpx.Response(200, json=[]))

    assert geocoder.by_postal_code("50-370") is None
    assert geocoder.by_postal_code("31-001") is None
    assert NominatimGeocoder._unavailable_until == 0.0


def test_nominatim_connection_error_is_geocoder_error(monkeypatch):
    monkeypatch.setattr("app.providers.geocoding.MIN_INTERVAL_SECONDS", 0)

    monkeypatch.setattr(NominatimGeocoder, "_unavailable_until", 0.0)

    def handler(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(GeocoderError):
        _nominatim(handler).by_town("Wrocław")


@pytest.mark.usefixtures("rates")
def test_saved_profile_gets_location_and_old_profile_is_located_on_read(client_a, user_a, db):
    saved = client_a.put("/api/v1/users/me/profile", json=profile_payload()).json()

    assert saved["base_info"]["location"]["source"] == "postal_region"
    assert saved["base_info"]["location"]["address"] == "50-370 Wrocław"

    row = db.get(UserProfileRow, user_a.id)
    row.base_info = {key: value for key, value in row.base_info.items() if key != "location"}
    db.commit()

    read = client_a.get("/api/v1/users/me/profile").json()
    db.expire_all()

    assert read["base_info"]["location"]["label"] == "Wrocław"
    assert db.get(UserProfileRow, user_a.id).base_info["location"]["source"] == "postal_region"


@pytest.mark.usefixtures("rates")
def test_approximate_location_is_retried_on_read_and_saved_when_found(client_a, user_a, db, monkeypatch):
    client_a.put("/api/v1/users/me/profile", json=profile_payload())
    assert client_a.get("/api/v1/users/me/profile").json()["base_info"]["location"]["approximate"] is True

    monkeypatch.setattr(geocoding, "default_geocoder", FakeGeocoder)
    read = client_a.get("/api/v1/users/me/profile").json()["base_info"]["location"]
    db.expire_all()

    assert (read["source"], read["approximate"]) == ("postal_code", False)
    assert db.get(UserProfileRow, user_a.id).base_info["location"]["source"] == "postal_code"


@pytest.mark.usefixtures("rates")
def test_profile_changes_keep_location_consistent(client_a, user_a, db, monkeypatch):
    geocoder = FakeGeocoder()
    monkeypatch.setattr(geocoding, "default_geocoder", lambda: geocoder)
    payload = profile_payload()

    first = client_a.put("/api/v1/users/me/profile", json=payload).json()["base_info"]["location"]
    payload["base_info"]["contracted_power_kw"] = 7
    payload["base_info"]["location"] = first
    same = client_a.put("/api/v1/users/me/profile", json=payload).json()["base_info"]["location"]
    payload["base_info"].update(town="Kraków", postal_code="31-001")
    moved = client_a.put("/api/v1/users/me/profile", json=payload).json()["base_info"]["location"]
    payload["base_info"]["location"] = {"latitude": 50.1, "longitude": 20.0, "source": "manual", "address": "31-001 Kraków"}
    manual = client_a.put("/api/v1/users/me/profile", json=payload).json()["base_info"]["location"]
    payload["base_info"]["location"] = {"latitude": 60.0, "longitude": 20.0, "source": "manual"}
    outside = client_a.put("/api/v1/users/me/profile", json=payload)

    assert same == first
    assert [call for call in geocoder.calls if call[0] == "postal_code"] == [("postal_code", "50-370"), ("postal_code", "31-001")]
    assert (moved["latitude"], moved["address"]) == (50.062, "31-001 Kraków")
    assert (manual["source"], manual["latitude"]) == ("manual", 50.1)
    assert outside.status_code == 422
    db.expire_all()
    assert db.get(UserProfileRow, user_a.id).base_info["location"]["source"] == "manual"


@pytest.mark.usefixtures("rates")
def test_deleting_account_removes_profile_with_location_and_panels(client_a, user_a, db):
    payload = profile_payload()
    payload["pv_config"] = {"mode": "net_billing", "installation": {"arrays": [{"power_kwp": 4}]}}
    client_a.put("/api/v1/users/me/profile", json=payload)
    user_id, email = user_a.id, user_a.email

    response = client_a.request("DELETE", "/api/v1/users/me", json={"confirm_email": email})
    db.expire_all()

    assert response.status_code == 204
    assert db.get(UserProfileRow, user_id) is None


@pytest.mark.usefixtures("rates")
def test_address_that_does_not_exist_is_not_saved(client_a, user_a, db, monkeypatch):
    monkeypatch.setattr(geocoding, "default_geocoder", FakeGeocoder)
    payload = profile_payload()
    client_a.put("/api/v1/users/me/profile", json=payload)
    payload["base_info"].update(town="Wronki", postal_code="51-515", contracted_power_kw=9)

    response = client_a.put("/api/v1/users/me/profile", json=payload)
    db.expire_all()

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "loc": ["body", "base_info", "town"],
            "msg": "Miejscowość Wronki nie pasuje do kodu pocztowego 51-515. Ten kod to okolice: Wrocław.",
            "type": "value_error",
        }
    ]
    saved = db.get(UserProfileRow, user_a.id).base_info
    assert (saved["town"], saved["contracted_power_kw"], saved["location"]["address"]) == ("Wrocław", 5.0, "50-370 Wrocław")


@pytest.mark.usefixtures("rates")
def test_old_profile_with_wrong_address_still_opens(client_a, user_a, db, monkeypatch):
    payload = profile_payload()
    payload["base_info"].update(town="Wronki", postal_code="51-515")
    db.add(UserProfileRow(user_id=user_a.id, **payload))
    db.commit()
    monkeypatch.setattr(geocoding, "default_geocoder", FakeGeocoder)

    response = client_a.get("/api/v1/users/me/profile")

    assert response.status_code == 200
    assert response.json()["base_info"]["location"]["approximate"] is True


LOOKUP_TOWNS = {
    "Wronki": [
        Place(52.71, 16.374, "Wronki", "64-510", "town"),
        Place(53.9, 22.1, "Wronki", None, "village"),
    ],
    "Wrocław": [Place(51.109, 17.033, "Wrocław", None, "city")],
    "Nowa Wieś": [Place(49.907, 19.216, "Nowa Wieś", None, "village"), Place(53.653, 20.61, "Nowa Wieś", "11-030", "village")],
    "Smolec": [Place(51.074, 16.884, "Smolec", "55-080", "village"), Place(51.0745, 16.8844, "Smolec", None, "village")],
    "Wrocławki": [Place(53.252, 18.604, "Wrocławki", None, "village")],
}


def test_postal_code_alone_fills_town_and_shows_location():
    result = lookup_address(None, "64-510", FakeGeocoder(postal={"64-510": Place(52.705, 16.345, "Wronki")}, towns=LOOKUP_TOWNS))

    assert (result.status, result.town, result.postal_code) == ("found", "Wronki", "64-510")
    assert (result.location.latitude, result.location.longitude) == (52.71, 16.374)


def test_unknown_postal_code_alone_is_marked():
    result = lookup_address(None, "99-999", FakeGeocoder())

    assert (result.status, set(result.errors)) == ("invalid", {"postal_code"})


def test_town_alone_fills_postal_code_when_it_is_the_only_town_with_that_name():
    result = lookup_address("Smolec", None, FakeGeocoder(towns=LOOKUP_TOWNS))

    assert (result.status, result.town, result.postal_code) == ("found", "Smolec", "55-080")


def test_town_without_postal_code_in_search_gets_code_confirmed_by_its_area():
    towns = {"Sobotka": [Place(50.899, 16.744, "Sobótka", None, "town")]}
    postal = {"55-050": Place(50.897, 16.751, "Sobótka")}

    result = lookup_address("Sobotka", None, FakeGeocoder(postal=postal, towns=towns, reverse={"Sobótka": "55-050"}))

    assert (result.status, result.town, result.postal_code) == ("found", "Sobótka", "55-050")
    assert "popraw" in result.message


def test_postal_code_of_neighbouring_town_is_not_filled():
    towns = {"Smolec": [Place(51.074, 16.884, "Smolec", None, "village")]}
    postal = {"54-560": Place(51.107, 16.886, "Wrocław")}

    result = lookup_address("Smolec", None, FakeGeocoder(postal=postal, towns=towns, reverse={"Smolec": "54-560"}))

    assert (result.status, result.town, result.postal_code) == ("found", "Smolec", None)
    assert "Wpisz kod pocztowy" in result.message


def test_city_postal_code_from_search_is_not_filled():
    towns = {"Legnica": [Place(51.21, 16.161, "Legnica", "59-220", "city")]}

    result = lookup_address("Legnica", None, FakeGeocoder(towns=towns))

    assert (result.status, result.postal_code) == ("found", None)
    assert "ma ich kilka" in result.message


def test_town_is_preferred_over_villages_with_the_same_name():
    result = lookup_address("wronki", None, FakeGeocoder(towns=LOOKUP_TOWNS))

    assert (result.status, result.town, result.postal_code) == ("found", "Wronki", "64-510")
    assert "wsie o nazwie wronki" in result.message.lower()


def test_many_villages_with_the_same_name_need_postal_code():
    result = lookup_address("Nowa Wieś", None, FakeGeocoder(towns=LOOKUP_TOWNS))

    assert (result.status, result.location, result.postal_code) == ("ambiguous", None, None)


def test_city_with_many_postal_codes_shows_location_and_asks_for_code():
    result = lookup_address("Wroclaw", None, FakeGeocoder(towns={"Wroclaw": LOOKUP_TOWNS["Wrocław"] + LOOKUP_TOWNS["Wrocławki"]}))

    assert (result.status, result.town, result.postal_code) == ("found", "Wrocław", None)
    assert result.location is not None and "kod pocztowy" in result.message


def test_town_and_postal_code_are_checked_together():
    found = lookup_address("Wrocław", "51-515", FakeGeocoder())
    wrong = lookup_address("Wronki", "51-515", FakeGeocoder())

    assert (found.status, found.town, found.location.source) == ("found", "Wrocław", LocationSource.POSTAL_CODE)
    assert (wrong.status, set(wrong.errors)) == ("invalid", {"town"})


def test_lookup_when_geocoder_does_not_answer():
    result = lookup_address("Wrocław", "51-515", FakeGeocoder(error=GeocoderError("timeout")))

    assert (result.status, result.location) == ("unavailable", None)


def test_address_lookup_endpoint_does_not_save_profile(client_a, anonymous_client, user_a, db, monkeypatch):
    monkeypatch.setattr(geocoding, "default_geocoder", FakeGeocoder)
    url = "/api/v1/users/me/profile/address-lookup"

    found = client_a.get(url, params={"postal_code": "51-515", "town": " Wrocław "})

    assert found.status_code == 200
    assert (found.json()["status"], found.json()["location"]["label"]) == ("found", "Wrocław")
    assert client_a.get(url).status_code == 422
    assert client_a.get(url, params={"postal_code": "51515"}).status_code == 422
    assert anonymous_client.get(url, params={"postal_code": "51-515"}).status_code == 401
    assert db.get(UserProfileRow, user_a.id) is None

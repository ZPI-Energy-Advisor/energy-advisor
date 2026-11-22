import logging
import unicodedata
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.providers import geocoding
from app.providers.geocoding import GeocoderError, Place, distance_km, region_anchor
from app.schemas.user_profile import BaseInfo, HomeLocation, LocationSource

logger = logging.getLogger(__name__)


class AddressError(Exception):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def _location(place: Place, source: LocationSource, label: str | None, address: str | None) -> HomeLocation:
    return HomeLocation(
        latitude=round(place.latitude, 4),
        longitude=round(place.longitude, 4),
        source=source,
        label=label[:200] if label else None,
        address=address,
    )


def _nearest(candidates: list[Place], point: Place) -> Place:
    return min(candidates, key=lambda candidate: distance_km(candidate, point))


SAME_PLACE_KM = 5.0
TOWN_KINDS = ("city", "town")


class AddressLookup(BaseModel):
    status: Literal["found", "invalid", "ambiguous", "unavailable"]
    town: str | None = None
    postal_code: str | None = None
    location: HomeLocation | None = None
    errors: dict[str, str] = {}
    message: str | None = None


def _plain(text: str) -> str:
    text = text.casefold().replace("ł", "l")
    return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))


def _distinct(places: list[Place]) -> list[Place]:
    kept: list[Place] = []
    for place in places:
        if all(distance_km(place, other) > SAME_PLACE_KM for other in kept):
            kept.append(place)
    return kept


def _verify(base_info: BaseInfo, geocoder) -> HomeLocation:
    return _verify_address(base_info.town, base_info.postal_code, geocoder)


def _verify_address(town: str, postal_code: str, geocoder) -> HomeLocation:
    address = f"{postal_code} {town}"
    area = geocoder.by_postal_code(postal_code)
    if area is not None:
        candidates = geocoder.by_town(town, near=area)
        if candidates:
            best = _nearest(candidates, area)
            return _location(best, LocationSource.POSTAL_CODE, best.name or town, address)
        hint = f" Ten kod to okolice: {area.name}." if area.name else ""
        raise AddressError({"town": f"Miejscowość {town} nie pasuje do kodu pocztowego {postal_code}.{hint}"})

    anchor = region_anchor(postal_code)
    candidates = geocoder.by_town(town)
    if not candidates:
        raise AddressError({
            "postal_code": f"Nie znaleźliśmy kodu pocztowego {postal_code}.",
            "town": f"Nie znaleźliśmy miejscowości {town}. Sprawdź pisownię.",
        })
    in_region = [c for c in candidates if distance_km(c, anchor) <= geocoding.MAX_TOWN_DISTANCE_KM]
    if not in_region:
        raise AddressError({"postal_code": f"Kod pocztowy {postal_code} nie pasuje do miejscowości {town}."})
    best = _nearest(in_region, anchor)
    return _location(best, LocationSource.TOWN, best.name or town, address)


def locate_home(base_info: BaseInfo, geocoder=None, strict: bool = True) -> HomeLocation:
    geocoder = geocoder or geocoding.default_geocoder()
    try:
        return _verify(base_info, geocoder)
    except AddressError:
        if strict:
            raise
    except (GeocoderError, ValidationError) as error:
        logger.warning("Nie udało się wyznaczyć współrzędnych dla %s: %s", base_info.postal_code, error)
    anchor = region_anchor(base_info.postal_code)
    return _location(anchor, LocationSource.POSTAL_REGION, anchor.name, base_info.address_key())


def stored_location(base_info: dict | None) -> HomeLocation | None:
    raw = (base_info or {}).get("location")
    if not raw:
        return None
    try:
        return HomeLocation.model_validate(raw)
    except ValidationError:
        return None


def resolve_location(base_info: BaseInfo, previous: HomeLocation | None, geocoder=None, strict: bool = True) -> HomeLocation:
    address = base_info.address_key()
    incoming = base_info.location
    manual = None
    if incoming and incoming.source == LocationSource.MANUAL and incoming.address in (None, address):
        manual = incoming.model_copy(update={"address": address, "label": None})
    reset = "location" in base_info.model_fields_set and incoming is None
    checked = previous is not None and not previous.approximate and previous.address == address
    if checked:
        if manual:
            return manual
        if not (reset and previous.source == LocationSource.MANUAL):
            return previous
    located = locate_home(base_info, geocoder, strict)
    return manual or located


def _from_postal_code(postal_code: str, geocoder) -> AddressLookup:
    area = geocoder.by_postal_code(postal_code)
    if area is None:
        return AddressLookup(status="invalid", errors={"postal_code": f"Nie znaleźliśmy kodu pocztowego {postal_code}."})
    if area.name:
        towns = geocoder.by_town(area.name, near=area)
        if towns:
            best = _nearest(towns, area)
            town = best.name or area.name
            return AddressLookup(
                status="found",
                town=town,
                postal_code=postal_code,
                location=_location(best, LocationSource.POSTAL_CODE, town, f"{postal_code} {town}"),
                message=f"Uzupełniliśmy miejscowość z kodu pocztowego. Jeśli mieszkasz w innej miejscowości z kodem {postal_code}, wpisz jej nazwę.",
            )
    return AddressLookup(
        status="found",
        town=area.name,
        postal_code=postal_code,
        location=_location(area, LocationSource.POSTAL_CODE, area.name, f"{postal_code} {area.name or ''}".strip()),
        message=None if area.name else "Wpisz miejscowość.",
    )


def _from_town(town: str, geocoder) -> AddressLookup:
    named = _distinct([place for place in geocoder.by_town(town) if place.name and _plain(place.name) == _plain(town)])
    if not named:
        return AddressLookup(status="invalid", errors={"town": f"Nie znaleźliśmy miejscowości {town}. Sprawdź pisownię."})
    note = None
    if len(named) > 1:
        towns = [place for place in named if place.kind in TOWN_KINDS]
        if len(towns) != 1:
            return AddressLookup(
                status="ambiguous",
                message=f"Jest kilka miejscowości o nazwie {town}. Wpisz kod pocztowy, żebyśmy wiedzieli, o którą chodzi.",
            )
        named = towns
        note = f"Są też wsie o nazwie {town}. Jeśli mieszkasz w jednej z nich, wpisz jej kod pocztowy."
    place = named[0]
    if place.postal_code is None:
        return AddressLookup(
            status="found",
            town=place.name,
            location=_location(place, LocationSource.TOWN, place.name, None),
            message=" ".join(filter(None, [f"Wpisz kod pocztowy: {place.name} może mieć ich kilka.", note])),
        )
    return AddressLookup(
        status="found",
        town=place.name,
        postal_code=place.postal_code,
        location=_location(place, LocationSource.POSTAL_CODE, place.name, f"{place.postal_code} {place.name}"),
        message=note,
    )


def lookup_address(town: str | None, postal_code: str | None, geocoder=None) -> AddressLookup:
    geocoder = geocoder or geocoding.default_geocoder()
    try:
        if town and postal_code:
            location = _verify_address(town, postal_code, geocoder)
            return AddressLookup(status="found", town=location.label or town, postal_code=postal_code, location=location)
        if postal_code:
            return _from_postal_code(postal_code, geocoder)
        return _from_town(town, geocoder)
    except AddressError as error:
        return AddressLookup(status="invalid", errors=error.errors)
    except (GeocoderError, ValidationError) as error:
        logger.warning("Nie udało się sprawdzić adresu: %s", error)
        return AddressLookup(
            status="unavailable",
            message="Nie udało się teraz sprawdzić adresu. Sprawdzimy go przy zapisie profilu.",
        )

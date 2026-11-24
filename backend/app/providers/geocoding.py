import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

NOMINATIM_URL = os.getenv("NOMINATIM_URL") or "https://nominatim.openstreetmap.org"
USER_AGENT = os.getenv("GEOCODER_USER_AGENT") or "energy-advisor/1.0 (+https://github.com/ZPI-Energy-Advisor/energy-advisor)"
TIMEOUT_SECONDS = 4.0
MIN_INTERVAL_SECONDS = 1.1
MAX_TOWN_DISTANCE_KM = 250.0
NEAR_POSTAL_CODE_DEGREES = 0.3
UNAVAILABLE_PAUSE_SECONDS = 300.0
# Ile odpowiedzi geokodera pamiętamy w procesie; najstarsze wypadają, żeby losowe zapytania nie zapełniły pamięci.
CACHE_LIMIT = 1000

POSTAL_REGIONS = {
    "0": ("Warszawa", 52.2297, 21.0122),
    "1": ("Olsztyn", 53.7784, 20.4801),
    "2": ("Lublin", 51.2465, 22.5684),
    "3": ("Kraków", 50.0647, 19.9450),
    "4": ("Katowice", 50.2649, 19.0238),
    "5": ("Wrocław", 51.1079, 17.0385),
    "6": ("Poznań", 52.4064, 16.9252),
    "7": ("Szczecin", 53.4285, 14.5528),
    "8": ("Gdańsk", 54.3520, 18.6466),
    "9": ("Łódź", 51.7592, 19.4560),
}


POSTAL_CODE = re.compile(r"^\d{2}-\d{3}$")
AREA_PREFIXES = ("gmina ", "miasto ")


@dataclass(frozen=True)
class Place:
    latitude: float
    longitude: float
    name: str | None = None
    postal_code: str | None = None
    kind: str | None = None


class GeocoderError(Exception):
    def __init__(self, message: str, unavailable: bool = False):
        super().__init__(message)
        self.unavailable = unavailable


def region_anchor(postal_code: str) -> Place:
    name, latitude, longitude = POSTAL_REGIONS[postal_code[0]]
    return Place(latitude, longitude, name)


class _LimitedCache(OrderedDict):
    def __init__(self, limit: int = CACHE_LIMIT):
        super().__init__()
        self.limit = limit

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self.limit:
            self.popitem(last=False)


def distance_km(a: Place, b: Place) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


class NominatimGeocoder:
    _lock = threading.Lock()
    _last_request = 0.0
    _unavailable_until = 0.0

    def __init__(self, client: httpx.Client | None = None, base_url: str = NOMINATIM_URL):
        self.client = client or httpx.Client(timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})
        self.base_url = base_url.rstrip("/")
        self._cache: _LimitedCache = _LimitedCache()

    def by_postal_code(self, postal_code: str) -> Place | None:
        key = ("postal_code", postal_code)
        if key not in self._cache:
            results = self._search({"postalcode": postal_code, "limit": 1, "addressdetails": 1})
            self._cache[key] = self._place(results[0], area=True) if results else None
        return self._cache[key]

    def by_town(self, town: str, near: Place | None = None) -> list[Place]:
        params = {"city": town, "limit": 10, "addressdetails": 1}
        if near is not None:
            d = NEAR_POSTAL_CODE_DEGREES
            params |= {
                "viewbox": f"{near.longitude - 1.5 * d},{near.latitude + d},{near.longitude + 1.5 * d},{near.latitude - d}",
                "bounded": 1,
            }
        key = ("town", town.casefold(), near and (round(near.latitude, 3), round(near.longitude, 3)))
        if key not in self._cache:
            self._cache[key] = [self._place(item) for item in self._search(params)]
        return self._cache[key]

    def postal_code_at(self, place: Place) -> str | None:
        key = ("reverse", round(place.latitude, 4), round(place.longitude, 4))
        if key not in self._cache:
            result = self._call("reverse", {"lat": place.latitude, "lon": place.longitude, "zoom": 18, "addressdetails": 1})
            postal_code = (result.get("address") or {}).get("postcode") if isinstance(result, dict) else None
            self._cache[key] = postal_code if isinstance(postal_code, str) and POSTAL_CODE.match(postal_code) else None
        return self._cache[key]

    def _search(self, params: dict) -> list[dict]:
        payload = self._call("search", {**params, "countrycodes": "pl"})
        if not isinstance(payload, list):
            raise GeocoderError("Nieoczekiwany format odpowiedzi geokodera")
        return payload

    def _call(self, endpoint: str, params: dict):
        if time.monotonic() < NominatimGeocoder._unavailable_until:
            raise GeocoderError("Geokoder był niedostępny przed chwilą; spróbujemy później")
        try:
            return self._request(endpoint, params)
        except GeocoderError as error:
            if getattr(error, "unavailable", False):
                NominatimGeocoder._unavailable_until = time.monotonic() + UNAVAILABLE_PAUSE_SECONDS
            raise

    def _request(self, endpoint: str, params: dict):
        with NominatimGeocoder._lock:
            wait = NominatimGeocoder._last_request + MIN_INTERVAL_SECONDS - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.client.get(
                    f"{self.base_url}/{endpoint}",
                    params={**params, "format": "jsonv2", "accept-language": "pl"},
                )
            except httpx.HTTPError as error:
                raise GeocoderError(f"Geokoder nie odpowiada: {error}", unavailable=True) from error
            finally:
                NominatimGeocoder._last_request = time.monotonic()
        if response.status_code != 200:
            raise GeocoderError(
                f"Geokoder zwrócił HTTP {response.status_code}",
                unavailable=response.status_code in (403, 429) or response.status_code >= 500,
            )
        try:
            return response.json()
        except ValueError as error:
            raise GeocoderError("Geokoder zwrócił niepoprawny JSON") from error

    @staticmethod
    def _place(item: dict, area: bool = False) -> Place:
        address = item.get("address") or {}
        name = item.get("name") or None
        if area:
            name = next(
                (address[key] for key in ("city", "town", "municipality", "village", "county") if address.get(key)),
                None,
            )
            for prefix in AREA_PREFIXES:
                if name and name.lower().startswith(prefix):
                    name = name[len(prefix):]
        postal_code = address.get("postcode")
        if not isinstance(postal_code, str) or not POSTAL_CODE.match(postal_code):
            postal_code = None
        try:
            return Place(float(item["lat"]), float(item["lon"]), name, postal_code, item.get("addresstype"))
        except (KeyError, TypeError, ValueError) as error:
            raise GeocoderError("Geokoder zwrócił wynik bez współrzędnych") from error


@lru_cache(maxsize=1)
def default_geocoder() -> NominatimGeocoder:
    return NominatimGeocoder()

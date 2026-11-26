"""Pogoda historyczna z Open-Meteo i produkcja PV wyliczona z niej dla generatora plików.

Model produkcji jest celowo bogatszy od modelu prognozy (ZP-118): temperatura ogniw, słabsza sprawność
przy małym nasłonecznieniu, zmienność w obrębie godziny, zabrudzenie i śnieg. Dzięki temu kalibracja
prognozy uczy się na danych, które wynikają z pogody, ale nie zgadzają się z nią w 100%.
"""

import json
import math
import random
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOUR = timedelta(hours=1)
QUARTER = timedelta(minutes=15)
DEFAULT_LATITUDE = 51.1
DEFAULT_LONGITUDE = 17.0

SYSTEM_EFFICIENCY = 0.83
TEMPERATURE_COEFFICIENT = -0.0037
CELL_HEATING_PER_W_M2 = 0.03
LOW_LIGHT_W_M2 = 200.0
LOW_LIGHT_LOSS = 0.15
QUARTER_VARIABILITY = 0.12
DAY_VARIABILITY = 0.04
SNOW_MIN_CM = 1.0
SNOW_MAX_TEMPERATURE = 1.0
SNOW_WINDOW = timedelta(hours=48)
# Opcja --weather-error: pogoda z archiwum to przybliżenie dla obszaru kilku km, a nie pomiar nad dachem, więc
# dzienna produkcja odbiega od niej tym bardziej, im więcej chmur (słonecznie ok. ±5%, pochmurno ok. ±30%).
# Jasność dnia to nasłonecznienie dnia względem najjaśniejszego dnia z ±15 dni (przybliżenie bezchmurnego nieba).
WEATHER_ERROR_CLEAR = 0.05
WEATHER_ERROR_OVERCAST = 0.30
CLEAR_SKY_WINDOW_DAYS = 15
# Mniej więcej raz na dwa miesiące falownik nie pracuje przez kilka godzin (awaria, wyłączenie, aktualizacja).
OUTAGE_PROBABILITY = 1 / 60
OUTAGE_QUARTERS = (12, 40)


@dataclass(frozen=True)
class Array:
    kwp: float
    tilt: int
    azimuth: int

    @classmethod
    def parse(cls, text: str) -> "Array":
        try:
            kwp, tilt, azimuth = text.split("/")
            array = cls(float(kwp), int(tilt), int(azimuth))
        except ValueError as error:
            raise ValueError(f"Grupa paneli „{text}”: oczekiwano KWP/NACHYLENIE/AZYMUT, np. 6/35/0") from error
        if not (0 < array.kwp <= 50 and 0 <= array.tilt <= 90 and -180 <= array.azimuth <= 180):
            raise ValueError(f"Grupa paneli „{text}”: moc 0–50 kWp, nachylenie 0–90°, azymut −180…180°")
        return array

    @property
    def key(self) -> str:
        if self.tilt == 0:
            return "0/0"
        return f"{self.tilt}/{180 if self.azimuth == -180 else self.azimuth}"


@dataclass
class Weather:
    latitude: float
    longitude: float
    start: datetime
    temperature_c: list[float | None]
    tilted_w_m2: dict[str, list[float | None]]
    snowfall_cm: list[float | None] = field(default_factory=list)

    def hour_index(self, moment: datetime) -> int | None:
        index = int((moment - self.start) / HOUR)
        return index if 0 <= index < len(self.temperature_c) else None

    def covers(self, start: datetime, end: datetime, keys: list[str]) -> bool:
        first, last = self.hour_index(start), self.hour_index(end - QUARTER)
        return (
            first is not None and last is not None and all(key in self.tilted_w_m2 for key in keys)
            and all(self.temperature_c[i] is not None for i in range(first, last + 1))
            and all(self.tilted_w_m2[key][i] is not None for key in keys for i in range(first, last + 1))
        )

    def to_json(self) -> str:
        return json.dumps({
            "source": "Open-Meteo Archive API (ERA5), godzinowo; wartość dotyczy godziny zaczynającej się w czasie start + i h",
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start": self.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "temperature_c": self.temperature_c,
            "tilted_w_m2": self.tilted_w_m2,
            "snowfall_cm": self.snowfall_cm,
        }, ensure_ascii=False, separators=(",", ":")) + "\n"

    @classmethod
    def load(cls, path: Path) -> "Weather":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            latitude=data["latitude"],
            longitude=data["longitude"],
            start=datetime.fromisoformat(data["start"].replace("Z", "+00:00")),
            temperature_c=data["temperature_c"],
            tilted_w_m2=data["tilted_w_m2"],
            snowfall_cm=data.get("snowfall_cm", []),
        )


def _get_json(url: str, params: dict) -> dict:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "energy-advisor-generator"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            reason = json.loads(error.read().decode("utf-8")).get("reason")
        except ValueError:
            reason = None
        raise ValueError(f"Open-Meteo odrzuciło zapytanie o pogodę: {reason or error.code}") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise ValueError(f"Nie udało się pobrać pogody z Open-Meteo: {error}") from error


def fetch_weather(latitude: float, longitude: float, start: datetime, end: datetime, arrays: list[Array],
                  get_json=_get_json) -> Weather:
    """Godziny [start, end) w UTC. Promieniowanie z Open-Meteo to średnia z godziny kończącej się w znaczniku,
    więc zapisujemy je przy godzinie, która się w nim kończy; temperatura jest chwilowa."""
    first_day = (start - HOUR).date()
    last_day = end.date()
    hours = int((end - start) / HOUR)
    temperature: list[float | None] = [None] * hours
    snowfall: list[float | None] = [None] * hours
    tilted: dict[str, list[float | None]] = {}
    for array in arrays:
        if array.key in tilted:
            continue
        tilt, azimuth = (int(part) for part in array.key.split("/"))
        data = get_json(ARCHIVE_URL, {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": first_day.isoformat(),
            "end_date": last_day.isoformat(),
            "timezone": "GMT",
            "hourly": "temperature_2m,global_tilted_irradiance,snowfall",
            "tilt": tilt,
            "azimuth": azimuth,
        })
        block = data.get("hourly") or {}
        times = [datetime.fromisoformat(value).replace(tzinfo=timezone.utc) for value in block.get("time", [])]
        series: list[float | None] = [None] * hours
        snow = block.get("snowfall") or [None] * len(times)
        for moment, gti, temp, cm in zip(times, block.get("global_tilted_irradiance", []), block.get("temperature_2m", []), snow):
            radiation_hour = int((moment - HOUR - start) / HOUR)
            if 0 <= radiation_hour < hours:
                series[radiation_hour] = gti
                if snowfall[radiation_hour] is None:
                    snowfall[radiation_hour] = cm
            temperature_hour = int((moment - start) / HOUR)
            if 0 <= temperature_hour < hours and temperature[temperature_hour] is None:
                temperature[temperature_hour] = temp
        tilted[array.key] = series
    return Weather(latitude, longitude, start, temperature, tilted, snowfall)


def _quarter_factors(rng: random.Random) -> list[float]:
    factors = [math.exp(rng.gauss(0, QUARTER_VARIABILITY)) for _ in range(4)]
    mean = sum(factors) / 4
    return [factor / mean for factor in factors]


def _array_kw(array: Array, irradiance: float, temperature: float) -> float:
    if irradiance <= 0:
        return 0.0
    cell = temperature + irradiance * CELL_HEATING_PER_W_M2
    thermal = 1 + TEMPERATURE_COEFFICIENT * (cell - 25)
    low_light = 1 - LOW_LIGHT_LOSS * max(0.0, 1 - irradiance / LOW_LIGHT_W_M2)
    return array.kwp * irradiance / 1000 * thermal * low_light


def _snow_on_panels(weather: Weather, day_start: datetime, day_end: datetime, temperatures: list[float]) -> bool:
    """Śnieg leży na panelach, gdy w ciągu ostatnich 48 h spadł (co najmniej 1 cm) i jest mróz."""
    if not weather.snowfall_cm or sum(temperatures) / len(temperatures) > SNOW_MAX_TEMPERATURE:
        return False
    first = max(0, int((day_start - SNOW_WINDOW - weather.start) / HOUR))
    last = weather.hour_index(day_end - QUARTER)
    return sum(cm or 0.0 for cm in weather.snowfall_cm[first:last + 1]) >= SNOW_MIN_CM


def _day_irradiance(weather: Weather, arrays: list[Array], first_hour: int, hours: int) -> float | None:
    if first_hour < 0:
        return None
    total = 0.0
    for array in arrays:
        values = weather.tilted_w_m2[array.key][first_hour:first_hour + hours]
        if len(values) < hours or any(value is None for value in values):
            return None
        total += array.kwp * sum(values)
    return total


def day_clearness(weather: Weather, arrays: list[Array], day_start: datetime, day_end: datetime) -> float:
    """Jasność dnia 0–1: nasłonecznienie dnia względem najjaśniejszego dnia z ±CLEAR_SKY_WINDOW_DAYS dni."""
    first = weather.hour_index(day_start)
    hours = weather.hour_index(day_end - QUARTER) + 1 - first
    today = _day_irradiance(weather, arrays, first, hours) or 0.0
    window = (_day_irradiance(weather, arrays, first + 24 * shift, hours)
              for shift in range(-CLEAR_SKY_WINDOW_DAYS, CLEAR_SKY_WINDOW_DAYS + 1))
    brightest = max((value for value in window if value is not None), default=0.0)
    return min(1.0, today / brightest) if brightest > 0 else 1.0


def day_production(weather: Weather, arrays: list[Array], inverter_kw: float, day_start: datetime,
                   day_end: datetime, rng: random.Random, weather_error: bool = False) -> list[float]:
    """Energia z falownika (kWh, dodatnia) na każdy kwadrans [day_start, day_end).

    Z weather_error dzień dostaje błąd danych pogodowych zależny od zachmurzenia, a rzadko kilkugodzinną
    przerwę falownika. Bez tej opcji losowanie jest takie jak wcześniej (te same pliki dla tego samego seeda)."""
    hours = range(weather.hour_index(day_start), weather.hour_index(day_end - QUARTER) + 1)
    temperatures = [weather.temperature_c[hour] for hour in hours]
    day_factor = math.exp(rng.gauss(0, DAY_VARIABILITY)) * SYSTEM_EFFICIENCY
    if _snow_on_panels(weather, day_start, day_end, temperatures):
        day_factor *= rng.uniform(0.0, 0.3)
    outage = range(0)
    if weather_error:
        clearness = day_clearness(weather, arrays, day_start, day_end)
        spread = WEATHER_ERROR_CLEAR + (WEATHER_ERROR_OVERCAST - WEATHER_ERROR_CLEAR) * (1 - clearness)
        day_factor *= math.exp(rng.gauss(0, spread))
        if rng.random() < OUTAGE_PROBABILITY:
            first_quarter = rng.randrange(6 * 4, 16 * 4)  # start przerwy między 6:00 a 16:00
            outage = range(first_quarter, first_quarter + rng.randint(*OUTAGE_QUARTERS))
    production = []
    moment = day_start
    while moment < day_end:
        hour = weather.hour_index(moment)
        factors = _quarter_factors(rng)
        for offset in range(4):
            if moment >= day_end:
                break
            temperature = weather.temperature_c[hour]
            dc = sum(
                _array_kw(array, weather.tilted_w_m2[array.key][hour] * factors[offset], temperature)
                for array in arrays
            )
            production.append(0.0 if len(production) in outage else min(dc * day_factor, inverter_kw) * 0.25)
            moment += QUARTER
    return production


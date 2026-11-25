import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.providers.prices.base import MARKET_TIMEZONE, local_day_bounds_utc
from app.services.weather_service import DayWeather, Quarter

FIXTURES = Path(__file__).parent / "fixtures"
DEVICES_DEMO = FIXTURES / "devices_demo_30d.json"
WEATHER_DEMO = FIXTURES / "weather_demo_30d.json"


def demo_production() -> dict[datetime, float]:
    document = json.loads(DEVICES_DEMO.read_text(encoding="utf-8"))
    production = {}
    for action in document["energy_usage"]:
        if action["device_id"] == "dev_pv_01":
            start = datetime.fromisoformat(action["action_start"]).astimezone(timezone.utc)
            for index, value in enumerate(action["profile_kwh"]):
                production[start + timedelta(minutes=15 * index)] = -value
    return production


def demo_weather_hours() -> tuple[datetime, list, list]:
    data = json.loads(WEATHER_DEMO.read_text(encoding="utf-8"))
    start = datetime.fromisoformat(data["start"].replace("Z", "+00:00"))
    return start, data["temperature_c"], data["tilted_w_m2"]["35/0"]


def demo_days(cell) -> dict[date, DayWeather]:
    start, temperatures, tilted = demo_weather_hours()
    days = {}
    for offset in range(30):
        day = date(2026, 10, 1) + timedelta(days=offset)
        first, end = local_day_bounds_utc(day)
        quarters = []
        moment = first
        while moment < end:
            hour = int((moment - start) / timedelta(hours=1))
            quarters.append(Quarter(moment, "archive", temperatures[hour], 0, tilted[hour], [tilted[hour]]))
            moment += timedelta(minutes=15)
        days[day] = DayWeather(day, cell, [], quarters, None)
    return days


def local_day(moment: datetime) -> date:
    return moment.astimezone(MARKET_TIMEZONE).date()

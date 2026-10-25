"""Generuje syntetyczny plik urządzeń (JSON) zgodny z docs/devices-file-format.md.

Użycie (z katalogu projektu):
    python backend/scripts/generate_devices_file.py --out devices.json
    python backend/scripts/generate_devices_file.py --start 2026-10-01 --days 30 --seed 42 \
        --devices full --with-pv --out backend/tests/fixtures/devices_demo_30d.json

Ten sam seed i te same parametry dają identyczny plik.
"""

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Warsaw")
SLOT = timedelta(minutes=15)
SLOT_HOURS = 0.25
# Środek Polski: wystarcza do wyznaczenia wschodu i zachodu słońca z dokładnością do kilkunastu minut.
LATITUDE = 52.0
LONGITUDE = 19.0
PV_PEAK_KWP = 6.0

# Względne zapotrzebowanie pompy ciepła na energię (październik = 1); latem zostaje sama CWU.
HEATING_FACTOR = {1: 2.0, 2: 1.8, 3: 1.5, 4: 0.9, 5: 0.4, 6: 0.15, 7: 0.12, 8: 0.12, 9: 0.35, 10: 1.0, 11: 1.5, 12: 1.9}
# Produkcja PV w bezchmurny dzień, kWh na kWp.
CLEAR_SKY_YIELD = {1: 1.4, 2: 2.4, 3: 3.7, 4: 5.0, 5: 5.8, 6: 6.2, 7: 6.0, 8: 5.3, 9: 4.1, 10: 2.9, 11: 1.7, 12: 1.1}
DARK_MONTHS = {10, 11, 12, 1, 2}
# (prawdopodobieństwo, zakres udziału produkcji bezchmurnej, zakres szumu na kwadrans)
WEATHER_DARK = [(0.25, (0.85, 1.0), (0.95, 1.0)), (0.35, (0.45, 0.7), (0.55, 1.0)), (0.40, (0.1, 0.3), (0.7, 1.0))]
WEATHER_BRIGHT = [(0.45, (0.85, 1.0), (0.95, 1.0)), (0.35, (0.45, 0.7), (0.55, 1.0)), (0.20, (0.1, 0.3), (0.7, 1.0))]

FIXED = {"mode": "fixed"}
DAYTIME_WINDOW = {"from": "07:00", "to": "22:00"}


def device(device_id, name, device_type, category, flexibility, max_power_kw=None, programs=None) -> dict:
    result = {"device_id": device_id, "device_name": name, "device_type": device_type, "device_category": category}
    if max_power_kw is not None:
        result["max_power_kw"] = max_power_kw
    result["flexibility"] = flexibility
    if programs:
        result["programs"] = programs
    return result


def program(program_id, name, profile_kwh) -> dict:
    return {"program_id": program_id, "program_name": name, "duration_min": len(profile_kwh) * 15,
            "profile_kwh": profile_kwh}


DEVICES = [
    device("dev_wm_01", "Pralka Bosch", "washing_machine", "AGD",
           {"mode": "shiftable", "allowed_window": DAYTIME_WINDOW},
           programs=[program("cotton_60", "Bawełna 60°C", [0.45, 0.45, 0.30, 0.10, 0.10, 0.15, 0.20, 0.20]),
                     program("quick_40", "Szybkie 40°C", [0.35, 0.25, 0.10, 0.10])]),
    device("dev_td_01", "Suszarka do ubrań Electrolux", "tumble_dryer", "AGD",
           {"mode": "shiftable", "allowed_window": DAYTIME_WINDOW},
           programs=[program("cotton_dry", "Bawełna do szafy", [0.30, 0.35, 0.35, 0.35, 0.30, 0.25, 0.15, 0.05])]),
    device("dev_dw_01", "Zmywarka Siemens", "dishwasher", "AGD",
           {"mode": "shiftable", "allowed_window": {"from": "19:00", "to": "07:00"}},
           programs=[program("eco", "Eco",
                             [0.15, 0.15, 0.05, 0.03, 0.03, 0.03, 0.03, 0.03, 0.12, 0.12, 0.06, 0.05])]),
    device("dev_ev_01", "Ładowarka EV", "ev_charger", "Pojazd elektryczny",
           {"mode": "interruptible", "allowed_window": {"from": "17:00", "to": "07:00"}}, max_power_kw=3.7),
    device("dev_hp_01", "Pompa ciepła Panasonic", "heat_pump", "Ogrzewanie",
           {"mode": "shiftable", "max_shift_min": 60}, max_power_kw=4.5),
    device("dev_pv_01", "Instalacja PV 6 kWp", "pv_inverter", "OZE", FIXED, max_power_kw=6.0),
    device("dev_vent_01", "Rekuperator", "ventilation", "Ogrzewanie", FIXED, max_power_kw=0.08),
    device("dev_fr_01", "Lodówka Samsung", "fridge", "AGD", FIXED, max_power_kw=0.15),
    device("dev_hob_01", "Płyta indukcyjna", "induction_hob", "AGD", FIXED, max_power_kw=7.2),
    device("dev_ov_01", "Piekarnik elektryczny", "oven", "AGD", FIXED, max_power_kw=3.0),
    device("dev_mw_01", "Kuchenka mikrofalowa", "microwave", "AGD", FIXED, max_power_kw=1.2),
    device("dev_kt_01", "Czajnik elektryczny", "kettle", "AGD", FIXED, max_power_kw=2.2),
    device("dev_cm_01", "Ekspres do kawy", "coffee_machine", "AGD", FIXED, max_power_kw=1.5),
    device("dev_lt_01", "Oświetlenie salon", "light", "Oświetlenie", FIXED, max_power_kw=0.12),
    device("dev_lt_02", "Oświetlenie kuchnia", "light", "Oświetlenie", FIXED, max_power_kw=0.08),
    device("dev_lt_03", "Oświetlenie sypialnia", "light", "Oświetlenie", FIXED, max_power_kw=0.06),
    device("dev_lt_04", "Oświetlenie łazienka", "light", "Oświetlenie", FIXED, max_power_kw=0.04),
    device("dev_lt_05", "Oświetlenie przedpokój", "light", "Oświetlenie", FIXED, max_power_kw=0.03),
    device("dev_lt_06", "Oświetlenie ogród", "light", "Oświetlenie", FIXED, max_power_kw=0.05),
    device("dev_tv_01", "Telewizor salon", "tv", "RTV/IT", FIXED, max_power_kw=0.15),
    device("dev_pc_01", "Komputer gabinet", "computer", "RTV/IT", FIXED, max_power_kw=0.25),
    device("dev_rt_01", "Router Wi-Fi", "router", "RTV/IT", FIXED, max_power_kw=0.012),
    device("dev_vc_01", "Odkurzacz", "vacuum_cleaner", "Inne", FIXED, max_power_kw=1.6),
    device("dev_hd_01", "Suszarka do włosów", "hair_dryer", "Inne", FIXED, max_power_kw=2.0),
]
PV_DEVICE = "dev_pv_01"
FULL_ONLY = {"dev_ev_01", "dev_hp_01", "dev_vent_01"}


def floor2(value: float) -> float:
    """Zaokrągla w dół do 0,01 kWh, żeby energia nigdy nie przekroczyła mocy maksymalnej."""
    return math.floor(value * 100 + 1e-9) / 100


def at(day: date, minutes: float) -> datetime:
    """Czas lokalny `minutes` od północy (może wypaść następnego dnia), zaokrąglony do kwadransa, w UTC."""
    local = datetime.combine(day, time(), TZ) + timedelta(minutes=round(minutes / 15) * 15)
    return local.astimezone(timezone.utc)


def sun_times(day: date) -> tuple[float, float]:
    """Wschód i zachód słońca jako czas zegarowy (minuty od północy), zgodnie z `at`."""
    n = day.timetuple().tm_yday
    declination = math.radians(23.44) * math.sin(2 * math.pi * (284 + n) / 365)
    latitude = math.radians(LATITUDE)
    cos_hour_angle = (math.sin(math.radians(-0.833)) - math.sin(latitude) * math.sin(declination)) / (
        math.cos(latitude) * math.cos(declination)
    )
    half_day = 4 * math.degrees(math.acos(max(-1.0, min(1.0, cos_hour_angle))))
    b = 2 * math.pi * (n - 81) / 364
    equation_of_time = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    noon = datetime.combine(day, time(), timezone.utc) + timedelta(minutes=720 - 4 * LONGITUDE - equation_of_time)
    local = [(noon + timedelta(minutes=sign * half_day)).astimezone(TZ) for sign in (-1, 1)]
    return tuple(moment.hour * 60 + moment.minute + moment.second / 60 for moment in local)


class House:
    """Zbiera akcje i pilnuje reguł: brak nakładania się akcji urządzenia i limit mocy przyłącza."""

    def __init__(self, start: datetime, end: datetime, max_grid_kw: float, devices: dict):
        self.start, self.end = start, end
        self.devices = devices
        self.load = [0.0] * int((end - start) / SLOT)
        self.limit = max_grid_kw * SLOT_HOURS
        self.busy = defaultdict(list)
        self.actions = []

    def add(self, device_id: str, start: datetime, profile: list[float], max_delay_slots: int = 0,
            deadline: datetime | None = None, **fields) -> datetime | None:
        """Dodaje akcję najwcześniej, jak się da (opóźniając o kwadranse). Zwraca jej koniec albo None."""
        if device_id not in self.devices or start < self.start:
            return None
        for delay in range(max_delay_slots + 1):
            begin = start + delay * SLOT
            end = begin + len(profile) * SLOT
            if end > self.end or (deadline and end > deadline):
                return None
            if self._fits(device_id, begin, end, profile):
                first = int((begin - self.start) / SLOT)
                for index, value in enumerate(profile):
                    self.load[first + index] += max(value, 0)
                self.busy[device_id].append((begin, end))
                self.actions.append({"device_id": device_id, "start": begin, "end": end, "deadline": deadline,
                                     **fields})
                return end
        return None

    def add_constant(self, device_id: str, start: datetime, end: datetime, energy: float, **kwargs):
        slots = int((end - start) / SLOT)
        if slots < 1 or energy < 0.01:
            return None
        return self.add(device_id, start, [energy / slots] * slots, energy=energy, **kwargs)

    def add_program(self, device_id: str, program_id: str, start: datetime, **kwargs):
        if device_id not in self.devices:
            return None
        profile = next(p["profile_kwh"] for p in self.devices[device_id]["programs"] if p["program_id"] == program_id)
        return self.add(device_id, start, profile, energy=round(sum(profile), 2), program_id=program_id, **kwargs)

    def _fits(self, device_id: str, begin: datetime, end: datetime, profile: list[float]) -> bool:
        if any(other_begin < end and begin < other_end for other_begin, other_end in self.busy[device_id]):
            return False
        first = int((begin - self.start) / SLOT)
        return all(value <= 0 or self.load[first + index] + value <= self.limit + 1e-9
                   for index, value in enumerate(profile))


class Generator:
    def __init__(self, house: House, start: date, days: int, rng: random.Random):
        self.house, self.rng = house, rng
        self.dates = [start + timedelta(days=offset) for offset in range(days)]
        self.weeks = [self._plan_week() for _ in range(math.ceil(days / 7))]

    def _plan_week(self) -> dict:
        rng = self.rng
        return {
            "home_office": set(rng.sample(range(7), 3)),
            "wash": set(rng.sample(range(7), rng.randint(2, 4))),
            "ev": set(rng.sample(range(7), rng.randint(3, 4))),
            "oven": set(rng.sample(range(7), rng.randint(2, 3))),
            "vacuum": set(rng.sample(range(7), rng.randint(1, 2))),
        }

    def run(self) -> None:
        for index, day in enumerate(self.dates):
            week = self.weeks[index // 7]
            self._day(day, {name: index % 7 in offsets for name, offsets in week.items()})

    def _constant(self, device_id: str, day: date, start_min: float, end_min: float, average_kw: float,
                  max_delay_slots: int = 2) -> None:
        """Akcja ze stałą średnią mocą `average_kw`, przycięta do mocy maksymalnej urządzenia."""
        start, end = at(day, start_min), at(day, end_min)
        hours = (end - start) / timedelta(hours=1)
        if hours <= 0 or device_id not in self.house.devices:
            return
        max_energy = self.house.devices[device_id]["max_power_kw"] * hours
        self.house.add_constant(device_id, start, end, floor2(min(average_kw * hours, max_energy)),
                                max_delay_slots=max_delay_slots)

    def _short(self, device_id: str, day: date, start_min: float, low: float, high: float, slots: int = 1) -> None:
        """Krótka akcja (np. czajnik) o energii losowanej z przedziału."""
        start = at(day, start_min)
        self.house.add_constant(device_id, start, start + slots * SLOT, floor2(self.rng.uniform(low, high)),
                                max_delay_slots=2)

    def _day(self, day: date, plan: dict) -> None:
        rng = self.rng
        weekend = day.weekday() >= 5
        home_office = plan["home_office"] and not weekend
        commute = not weekend and not home_office
        wake = rng.choice([360, 375, 390]) if not weekend else rng.choice([450, 480, 510, 540])
        leave = wake + 75 if commute else None
        back = rng.choice([1020, 1035, 1050, 1065, 1080]) if commute else None
        bedtime = rng.choice([1350, 1365, 1380, 1395]) + (30 if weekend else 0)
        dinner = back + 30 if commute else rng.choice([1050, 1080, 1110])
        sunrise, sunset = sun_times(day)

        self._always_on(day)
        self._lights(day, wake, leave, back, bedtime, sunrise, sunset)
        self._kitchen(day, plan, wake, dinner, weekend, home_office or weekend)
        self._other_appliances(day, plan, wake, back, bedtime, weekend, home_office)
        self._laundry_and_dishes(day, plan, back, bedtime, dinner, weekend, home_office)
        self._heat_pump(day)
        self._ev(day, plan, back, weekend, home_office)
        self._pv(day, sunrise, sunset)

    def _always_on(self, day: date) -> None:
        start, end = at(day, 0), at(day + timedelta(days=1), 0)
        hours = (end - start) / timedelta(hours=1)
        fridge = self.rng.uniform(0.92, 1.08) * (1.12 if day.month in (6, 7, 8) else 1.0)
        for device_id, daily_kwh in (("dev_fr_01", fridge), ("dev_rt_01", self.rng.uniform(0.26, 0.27)),
                                     ("dev_vent_01", self.rng.uniform(0.78, 0.88))):
            self.house.add_constant(device_id, start, end, floor2(daily_kwh * hours / 24))

    def _lights(self, day, wake, leave, back, bedtime, sunrise, sunset) -> None:
        rng = self.rng
        dark_morning = wake < sunrise + 20
        morning_end = min(sunrise + 20, leave if leave else wake + 120)
        evening = max(sunset - 15, back or 0)
        power = {device_id: d["max_power_kw"] for device_id, d in self.house.devices.items() if d["device_type"] == "light"}
        if dark_morning:
            for device_id, start in (("dev_lt_01", wake + 15), ("dev_lt_02", wake), ("dev_lt_05", wake)):
                self._constant(device_id, day, start, morning_end, power.get(device_id, 0) * rng.uniform(0.8, 0.95))
            self._constant("dev_lt_03", day, wake - 15, wake + 15, power.get("dev_lt_03", 0) * 0.9)
        self._constant("dev_lt_04", day, wake, wake + 45, power.get("dev_lt_04", 0) * 0.8)
        self._constant("dev_lt_04", day, bedtime - 60, bedtime - 15, power.get("dev_lt_04", 0) * 0.8)
        if evening < bedtime:
            self._constant("dev_lt_01", day, evening, bedtime, power.get("dev_lt_01", 0) * rng.uniform(0.8, 0.9))
            self._constant("dev_lt_02", day, evening, max(evening + 60, 1260), power.get("dev_lt_02", 0) * 0.75)
            self._constant("dev_lt_05", day, evening, bedtime - 30, power.get("dev_lt_05", 0) * 0.7)
        self._constant("dev_lt_03", day, bedtime - 45, bedtime + 15, power.get("dev_lt_03", 0) * 0.85)
        if sunset < 1365:
            self._constant("dev_lt_06", day, sunset, 1380, power.get("dev_lt_06", 0) * 0.98)

    def _kitchen(self, day, plan, wake, dinner, weekend, home_daytime) -> None:
        rng = self.rng
        self._short("dev_kt_01", day, wake + 15, 0.10, 0.13)
        self._short("dev_cm_01", day, wake + 30, 0.04, 0.06)
        if rng.random() < 0.5:
            self._short("dev_hob_01", day, wake + 30, 0.20, 0.30)
        if home_daytime:
            if rng.random() < 0.7:
                self._short("dev_mw_01", day, rng.choice([735, 765, 795]), 0.09, 0.13)
            if rng.random() < 0.7:
                self._short("dev_kt_01", day, rng.choice([840, 900, 960]), 0.09, 0.11)
            if rng.random() < 0.5:
                self._short("dev_cm_01", day, rng.choice([810, 870]), 0.03, 0.05)
        if weekend and rng.random() < 0.6:
            self._short("dev_hob_01", day, 780, 0.90, 1.10, slots=3)
        self._short("dev_hob_01", day, dinner, 0.85, 1.20, slots=3)
        if plan["oven"]:
            self._short("dev_ov_01", day, dinner + 15, 1.40, 1.80, slots=4)
        if rng.random() < 0.8:
            self._short("dev_kt_01", day, rng.choice([1170, 1200, 1230, 1260, 1290]), 0.10, 0.12)

    def _other_appliances(self, day, plan, wake, back, bedtime, weekend, home_office) -> None:
        rng = self.rng
        tv_start = rng.choice([1080, 1110, 1140]) if weekend else rng.choice([1170, 1200, 1230])
        self._constant("dev_tv_01", day, tv_start, bedtime - 15, 0.15 * 0.85)
        if home_office:
            self._constant("dev_pc_01", day, rng.choice([510, 525, 540]), rng.choice([960, 990, 1020]),
                           rng.uniform(0.13, 0.16))
        elif weekend and rng.random() < 0.5:
            start = rng.choice([900, 960, 1020])
            self._constant("dev_pc_01", day, start, start + 120, 0.18)
        if plan["vacuum"]:
            self._short("dev_vc_01", day, 600 if weekend or home_office else max(back or 0, 1110), 0.50, 0.60, slots=2)
        if not weekend or rng.random() < 0.6:
            self._short("dev_hd_01", day, wake + 15, 0.15, 0.22)

    def _laundry_and_dishes(self, day, plan, back, bedtime, dinner, weekend, home_office) -> None:
        rng = self.rng
        if plan["wash"]:
            if weekend:
                start = rng.choice([600, 630, 660, 690, 720])
            elif home_office:
                start = rng.choice([540, 570, 600, 630, 660, 690])
            else:
                start = back + rng.choice([30, 45, 60, 90])
            program_id = "cotton_60" if rng.random() < 0.6 else "quick_40"
            wash_end = self.house.add_program("dev_wm_01", program_id, at(day, start), max_delay_slots=8)
            if wash_end and rng.random() < 0.5:
                self.house.add_program("dev_td_01", "cotton_dry", wash_end + SLOT, max_delay_slots=4)
        # Zmywanie zaraz po kolacji kończy się przed północą, późne przechodzi na kolejną dobę.
        dishwasher_start = rng.choice([dinner + 60, dinner + 90, bedtime - 60, bedtime - 30])
        self.house.add_program("dev_dw_01", "eco", at(day, dishwasher_start), max_delay_slots=4)

    def _heat_pump(self, day: date) -> None:
        rng = self.rng
        factor = HEATING_FACTOR[day.month]
        for start_min, base_kwh in ((rng.choice([210, 225, 240, 255, 270]), 5.0),
                                    (rng.choice([990, 1005, 1020, 1035, 1050]), 3.8)):
            energy = floor2(base_kwh * factor * rng.uniform(0.85, 1.15))
            slots = max(4, min(28, math.ceil(energy / (1.6 * SLOT_HOURS))))
            start = at(day, start_min)
            self.house.add_constant("dev_hp_01", start, start + slots * SLOT, energy, max_delay_slots=4)

    def _ev(self, day, plan, back, weekend, home_office) -> None:
        if not plan["ev"] or "dev_ev_01" not in self.house.devices:
            return
        rng = self.rng
        if weekend:
            plugged_min = rng.choice([840, 900, 960, 1020])
        elif home_office:
            plugged_min = rng.choice([1080, 1110, 1140, 1170])
        else:
            plugged_min = back + rng.choice([0, 15])
        next_day = day + timedelta(days=1)
        departure = rng.choice([390, 420, 450]) if next_day.weekday() < 5 else rng.choice([540, 570, 600])
        plugged_in, deadline = at(day, plugged_min), at(next_day, departure)
        energy = floor2(rng.uniform(6.0, 15.0))
        slots = math.ceil(energy / (self.house.devices["dev_ev_01"]["max_power_kw"] * SLOT_HOURS))
        start = plugged_in + (SLOT if rng.random() < 0.25 else timedelta(0))
        self.house.add("dev_ev_01", start, [energy / slots] * slots, max_delay_slots=96, deadline=deadline,
                       energy=energy, plugged_in=plugged_in)

    def _pv(self, day: date, sunrise: float, sunset: float) -> None:
        if PV_DEVICE not in self.house.devices:
            return
        rng = self.rng
        weather = WEATHER_DARK if day.month in DARK_MONTHS else WEATHER_BRIGHT
        draw, cumulative = rng.random(), 0.0
        for probability, share_range, noise_range in weather:
            cumulative += probability
            if draw <= cumulative:
                break
        total = PV_PEAK_KWP * CLEAR_SKY_YIELD[day.month] * rng.uniform(*share_range)
        first, last = math.ceil(sunrise / 15), math.floor(sunset / 15)
        slots = last - first
        if slots < 1:
            return
        weights = [math.sin(math.pi * (k + 0.5) / slots) for k in range(slots)]
        slot_limit = self.house.devices[PV_DEVICE]["max_power_kw"] * SLOT_HOURS
        # + 0.0 zamienia -0.0 na 0.0
        profile = [-round(min(total * w / sum(weights) * rng.uniform(*noise_range), slot_limit), 2) + 0.0
                   for w in weights]
        while profile and profile[0] == 0:
            profile.pop(0)
            first += 1
        while profile and profile[-1] == 0:
            profile.pop()
        if profile:
            self.house.add(PV_DEVICE, at(day, first * 15), profile, energy=round(sum(profile), 2),
                           profile_kwh=profile)


def local_iso(moment: datetime) -> str:
    return moment.astimezone(TZ).isoformat()


def build_document(house: House) -> dict:
    actions = sorted(house.actions, key=lambda action: (action["start"], action["device_id"]))
    width = max(4, len(str(len(actions))))
    energy_usage = []
    for number, action in enumerate(actions, start=1):
        entry = {"action_id": f"act_{number:0{width}d}", "device_id": action["device_id"]}
        if "program_id" in action:
            entry["program_id"] = action["program_id"]
        if "plugged_in" in action:
            entry["plugged_in"] = local_iso(action["plugged_in"])
        entry["action_start"] = local_iso(action["start"])
        entry["action_end"] = local_iso(action["end"])
        entry["energy_kwh"] = action["energy"]
        if "profile_kwh" in action:
            entry["profile_kwh"] = action["profile_kwh"]
        if action["deadline"]:
            entry["deadline"] = local_iso(action["deadline"])
        energy_usage.append(entry)
    return {
        "period": {"start": local_iso(house.start), "end": local_iso(house.end)},
        "devices": list(house.devices.values()),
        "energy_usage": energy_usage,
    }


def dump(value, indent: int = 0, key: str | None = None) -> str:
    """JSON w układzie pliku przykładowego: krótkie obiekty i listy liczb w jednej linii."""
    pad = "  " * indent
    if isinstance(value, dict):
        if key == "allowed_window" or (key == "flexibility" and value == FIXED):
            return "{ " + ", ".join(f"{json.dumps(k)}: {dump(v, 0, k)}" for k, v in value.items()) + " }"
        items = [f"{pad}  {json.dumps(k, ensure_ascii=False)}: {dump(v, indent + 1, k)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list):
        if value and all(isinstance(item, (int, float)) for item in value):
            numbers = [f"{item:.2f}" for item in value]
            rows = [", ".join(numbers[i:i + 12]) for i in range(0, len(numbers), 12)]
            return "[" + (",\n" + " " * (len(pad) + len(json.dumps(key)) + 3)).join(rows) + "]"
        items = [f"{pad}  {dump(item, indent + 1)}" for item in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    if key == "energy_kwh":
        return f"{value:.2f}"
    return json.dumps(value, ensure_ascii=False)


def generate(start: date, days: int, seed: int, device_set: str, with_pv: bool, max_grid_kw: float) -> str:
    devices = {
        d["device_id"]: d for d in DEVICES
        if (d["device_id"] != PV_DEVICE or with_pv) and (device_set == "full" or d["device_id"] not in FULL_ONLY)
    }
    period_start = datetime.combine(start, time(), TZ).astimezone(timezone.utc)
    period_end = datetime.combine(start + timedelta(days=days), time(), TZ).astimezone(timezone.utc)
    house = House(period_start, period_end, max_grid_kw, devices)
    Generator(house, start, days, random.Random(seed)).run()
    return dump(build_document(house)) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generator syntetycznego pliku urządzeń (JSON).")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 1), help="pierwsza doba (RRRR-MM-DD)")
    parser.add_argument("--days", type=int, default=30, help="liczba dób (domyślnie 30)")
    parser.add_argument("--seed", type=int, default=42, help="ziarno losowania (domyślnie 42)")
    parser.add_argument("--devices", choices=["standard", "full"], default="full",
                        help="standard: bez EV, pompy ciepła i rekuperatora; full: wszystkie urządzenia")
    parser.add_argument("--with-pv", action="store_true", help="dodaje instalację PV")
    parser.add_argument("--max-grid-kw", type=float, default=9.0, help="limit mocy przyłącza (domyślnie 9 kW)")
    parser.add_argument("--out", required=True, help="ścieżka pliku wynikowego")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days musi być dodatnie")

    content = generate(args.start, args.days, args.seed, args.devices, args.with_pv, args.max_grid_kw)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print(f"Zapisano {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

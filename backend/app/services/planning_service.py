"""Wymagania na jutro (ZP-111): ustawienia użytkownika dla jego urządzeń, które da się planować.

Ustawienia zawierają tylko to, co wybrał użytkownik; resztę (urządzenia bez zapisanych preferencji,
domyślne przedziały) uzupełniamy z urządzeń z plików przy każdym odczycie, więc nowy plik urządzeń
od razu pojawia się na ekranie. Każdy zapis nadpisuje poprzedni.

Pompa ciepła i bojler (ZP-112) nie mają przedziałów ani programów: plan bierze ich energię z historii,
a użytkownik podaje tylko, o ile można przesunąć grzanie albo na kiedy woda ma być ciepła.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status

from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceProgram import DeviceProgram
from app.models.User import User
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.home_repository import clock_text
from app.repositories.planning_repository import EV_DEVICE_TYPE, PlanningRepository
from app.schemas.planning import (
    DevicePreference,
    PlanningDevice,
    PlanningPreferences,
    PlanningPreferencesOut,
    TimeWindow,
)
from app.schemas.smart_home import HomeDeviceProgram
from app.services.plan_history import average_daily_energy, daily_energy, reference_day
from app.services.scheduling import DRYER_AFTER_WASH
from app.services.water_heater import daily_draw_kwh, default_tank_liters, draw_from_history

HEAT_PUMP_TYPE = "heat_pump"
WATER_HEATER_TYPE = "water_heater"
# Bojler: woda gotowa rano i na wieczór; pompa ciepła: przesunięcie jak `max_shift_min` z pliku albo 1 h.
DEFAULT_READY_TIMES = ["06:00", "18:00"]
# Bez profilu liczymy bojler dla 2 osób.
DEFAULT_RESIDENTS = 2
# Historia bojlera: średnie zużycie z tylu ostatnich dni w plikach.
WATER_HEATER_HISTORY_DAYS = 7
DEFAULT_SHIFT_HOURS = 1
# Z sieci trzeba pobrać więcej, niż trafi do baterii: ładowanie AC traci ok. 10%.
CHARGING_EFFICIENCY = 0.9
DAY_MINUTES = 24 * 60
WHOLE_DAY = TimeWindow(start="00:00", end="00:00")
# „Wykonaj po”: urządzenie rusza najwyżej tyle minut po końcu poprzednika (jak suszarka po pralce).
AFTER_MAX_GAP_MIN = int(DRYER_AFTER_WASH.total_seconds() // 60)


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def window_span(window: TimeWindow) -> tuple[int, int]:
    """Minuty od północy jutrzejszej doby [start, koniec); koniec nie później niż start przechodzi przez północ."""
    start, end = _minutes(window.start), _minutes(window.end)
    return start, end if end > start else end + DAY_MINUTES


def _length(window: TimeWindow) -> int:
    start, end = window_span(window)
    return end - start


def _hours_text(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def _kwh_text(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def tomorrow() -> date:
    return datetime.now(LOCAL_TIMEZONE).date() + timedelta(days=1)


def device_kind(device: DeviceInstance) -> str:
    if device.device_type == EV_DEVICE_TYPE:
        return "ev"
    if device.device_type in (HEAT_PUMP_TYPE, WATER_HEATER_TYPE):
        return device.device_type
    return "program"


def default_preference(device: DeviceInstance, windows: list[TimeWindow]) -> DevicePreference:
    """Ustawienia przed pierwszym zapisem. Pompa ciepła i bojler i tak pracują codziennie, więc są od razu
    zaznaczone; urządzenia z programem i auto zaznacza użytkownik."""
    kind = device_kind(device)
    if kind == HEAT_PUMP_TYPE:
        hours = round((device.max_shift_min or 0) / 60) or DEFAULT_SHIFT_HOURS
        return DevicePreference(device_id=device.source_device_id, enabled=True, shift_hours=min(max(hours, 1), 3))
    if kind == WATER_HEATER_TYPE:
        return DevicePreference(device_id=device.source_device_id, enabled=True, ready_times=DEFAULT_READY_TIMES)
    return DevicePreference(device_id=device.source_device_id, windows=windows)


def default_windows(device: DeviceInstance) -> list[TimeWindow]:
    if device.allowed_window_from is None or device.allowed_window_to is None:
        return [WHOLE_DAY]
    return [TimeWindow(start=clock_text(device.allowed_window_from), end=clock_text(device.allowed_window_to))]


def energy_needed_kwh(preference: DevicePreference) -> float | None:
    """Energia z sieci do naładowania auta: wprost albo z różnicy poziomu baterii i strat ładowania."""
    if preference.energy_input == "kwh":
        return preference.energy_kwh
    if preference.battery_kwh is None or preference.current_percent is None or preference.target_percent is None:
        return None
    if preference.target_percent <= preference.current_percent:
        return None
    stored = (preference.target_percent - preference.current_percent) / 100 * preference.battery_kwh
    return round(stored / CHARGING_EFFICIENCY, 2)


class PlanningService:
    def __init__(self, repository: PlanningRepository, today: Callable[[], date] = tomorrow):
        self.repository = repository
        # Dzień planu: jutro (w testach stały), od niego zależy dzień tygodnia historii pompy i bojlera.
        self.plan_date = today

    def get(self, user: User) -> PlanningPreferencesOut:
        template = self.repository.get_template(user.id)
        saved = {item["device_id"]: DevicePreference.model_validate(item) for item in (template.devices if template else [])}
        return self._out(user, saved, template.updated_at if template else None)

    def save(self, user: User, preferences: PlanningPreferences) -> PlanningPreferencesOut:
        flexible = self.repository.flexible_devices(user.id)
        devices = {device.source_device_id: (device, programs) for device, programs in flexible}
        errors = []
        seen = set()
        for index, preference in enumerate(preferences.devices):
            if preference.device_id in seen:
                errors.append(_error(index, "device_id", "Urządzenie występuje w szablonie dwa razy."))
                continue
            seen.add(preference.device_id)
            if preference.device_id not in devices:
                errors.append(_error(index, "device_id", "Tego urządzenia nie ma w Twoich plikach albo nie da się go planować."))
                continue
            errors.extend(self._validate(index, preference, *devices[preference.device_id]))
        if not errors:
            errors.extend(_validate_order(preferences.devices, devices))
        if errors:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=errors)

        template = self.repository.save_template(
            user.id, [preference.model_dump(mode="json") for preference in preferences.devices]
        )
        saved = {preference.device_id: preference for preference in preferences.devices}
        return self._out(user, saved, template.updated_at, flexible)

    def _out(
        self, user: User, saved: dict[str, DevicePreference], saved_at, flexible: list | None = None
    ) -> PlanningPreferencesOut:
        """Odpowiedź z urządzeniami użytkownika; `save` podaje urządzenia już pobrane do walidacji."""
        devices = []
        if flexible is None:
            flexible = self.repository.flexible_devices(user.id)
        with_programs = {device.source_device_id for device, programs in flexible if programs}
        auto = [device for device, _ in flexible if device_kind(device) in (HEAT_PUMP_TYPE, WATER_HEATER_TYPE)]
        history = self.repository.device_actions([device.id for device in auto])
        residents = self.repository.residents(user.id) or DEFAULT_RESIDENTS
        plan_date = self.plan_date()
        for device, programs in flexible:
            defaults = default_windows(device)
            kind = device_kind(device)
            preference = saved.get(device.source_device_id) or default_preference(device, defaults)
            if not preference.windows and kind in ("program", "ev"):
                preference = preference.model_copy(update={"windows": defaults})
            # Pojemność z pliku jest faktem o urządzeniu, więc wygrywa z ustawieniem; bez niej domyślna z liczby osób.
            tank_from_file = round(device.tank_liters) if kind == WATER_HEATER_TYPE and device.tank_liters else None
            if tank_from_file:
                preference = preference.model_copy(update={"tank_liters": tank_from_file})
            elif kind == WATER_HEATER_TYPE and preference.tank_liters is None:
                preference = preference.model_copy(update={"tank_liters": default_tank_liters(residents)})
            if preference.after_device_id is not None and preference.after_device_id not in with_programs:
                # Urządzenia, na które czekało, nie ma już w plikach.
                preference = preference.model_copy(update={"after_device_id": None})
            is_ev = kind == "ev"
            history_day, history_kwh, hot_water_kwh, hot_water_source = None, None, None, None
            if kind == HEAT_PUMP_TYPE:
                history_day = reference_day(history.get(device.id, []), plan_date)
                history_kwh = daily_energy(history[device.id], history_day) if history_day else None
            elif kind == WATER_HEATER_TYPE:
                # Ciepła woda z historii bojlera (zużycie z termostatem minus jego straty), a bez niej z liczby osób.
                history_kwh, days = average_daily_energy(history.get(device.id, []), WATER_HEATER_HISTORY_DAYS)
                history_day = days[-1] if days else None
                if history_kwh:
                    hot_water_kwh, hot_water_source = draw_from_history(history_kwh, preference.tank_liters), "history"
                else:
                    hot_water_kwh, hot_water_source = daily_draw_kwh(residents), "residents"
            devices.append(PlanningDevice(
                device_id=device.source_device_id,
                device_name=device.name,
                device_type=device.device_type,
                device_category=device.device_category,
                flexibility_mode=device.flexibility_mode,
                max_power_kw=device.max_power_kw,
                programs=[
                    HomeDeviceProgram(program_id=p.source_program_id, program_name=p.name, duration_min=p.duration_min)
                    for p in programs
                ],
                default_windows=defaults,
                is_ev=is_ev,
                kind=kind,
                preference=preference,
                history_day=history_day,
                history_kwh=history_kwh,
                residents=residents if kind == WATER_HEATER_TYPE else None,
                tank_liters_from_file=tank_from_file,
                hot_water_kwh=round(hot_water_kwh, 2) if hot_water_kwh is not None else None,
                hot_water_source=hot_water_source,
                energy_needed_kwh=energy_needed_kwh(preference) if is_ev else None,
            ))
        return PlanningPreferencesOut(
            saved_at=saved_at,
            charging_efficiency=CHARGING_EFFICIENCY,
            after_max_gap_min=AFTER_MAX_GAP_MIN,
            devices=devices,
            flat_tariff=self.repository.flat_tariff(user.id),
        )

    @staticmethod
    def _validate(
        index: int, preference: DevicePreference, device: DeviceInstance, programs: list[DeviceProgram]
    ) -> list[dict]:
        errors = []
        # Wyłączone urządzenie zachowuje ustawienia bez sprawdzania, żeby dało się je zapisać w trakcie edycji
        # (jego karta jest zwinięta, więc błędu i tak nie byłoby widać).
        if not preference.enabled:
            return errors
        kind = device_kind(device)
        if kind == HEAT_PUMP_TYPE:
            # O ile przesunąć grzanie, planer wie sam (z pliku urządzeń albo domyślnie), więc nie pytamy.
            if len(set(preference.ready_times)) != len(preference.ready_times):
                errors.append(_error(index, "ready_times", "Godziny się powtarzają."))
            return errors
        if kind == WATER_HEATER_TYPE:
            if not preference.ready_times:
                errors.append(_error(index, "ready_times", "Dodaj co najmniej jedną godzinę."))
            elif len(set(preference.ready_times)) != len(preference.ready_times):
                errors.append(_error(index, "ready_times", "Godziny się powtarzają."))
            return errors
        is_ev = device.device_type == EV_DEVICE_TYPE
        if is_ev and preference.energy_input == "percent" and preference.current_percent is not None \
                and preference.target_percent is not None and preference.target_percent <= preference.current_percent:
            errors.append(_error(index, "target_percent", "Docelowy poziom baterii musi być wyższy niż obecny."))
        if preference.after_device_id is not None and programs:
            # Start wyznacza poprzednik: przedziałów nie sprawdzamy, czas sprawdza _validate_order.
            if _program(preference, programs) is None:
                errors.append(_error(index, "program_id", "Wybierz program."))
            return errors

        if not preference.windows:
            errors.append(_error(index, "windows", "Dodaj co najmniej jeden przedział godzin."))
            return errors
        spans = sorted(window_span(window) for window in preference.windows)
        if any(next_start < previous_end for (_, previous_end), (next_start, _) in zip(spans, spans[1:])):
            errors.append(_error(index, "windows", "Przedziały godzin nachodzą na siebie."))
            return errors
        longest = max(_length(window) for window in preference.windows)

        if programs:
            program = _program(preference, programs)
            if program is None:
                errors.append(_error(index, "program_id", "Wybierz program."))
            elif program.duration_min > longest:
                errors.append(_error(
                    index, "windows",
                    f"Najdłuższy przedział ({_hours_text(longest)}) jest krótszy niż program "
                    f"{program.name} ({_hours_text(program.duration_min)}).",
                ))

        if is_ev:
            energy = energy_needed_kwh(preference)
            if energy is None:
                if not any(error["loc"][-1] == "target_percent" for error in errors):
                    field = "energy_kwh" if preference.energy_input == "kwh" else "battery_kwh"
                    errors.append(_error(index, field, "Podaj, ile energii potrzebuje auto."))
            elif device.max_power_kw:
                total_hours = sum(_length(window) for window in preference.windows) / 60
                capacity = device.max_power_kw * total_hours
                if energy > capacity + 1e-9:
                    errors.append(_error(
                        index, "windows",
                        f"W przedziałach zmieści się najwyżej {_kwh_text(capacity)} kWh "
                        f"({_kwh_text(device.max_power_kw)} kW × {_hours_text(round(total_hours * 60))}), "
                        f"a auto potrzebuje {_kwh_text(energy)} kWh.",
                    ))
        return errors


def _program(preference: DevicePreference, programs: list[DeviceProgram]) -> DeviceProgram | None:
    return next((p for p in programs if p.source_program_id == preference.program_id), None)


def _starts(preference: DevicePreference, duration: int) -> set[int]:
    """Kwadranse, w których program może ruszyć, żeby zmieścić się w jednym z przedziałów."""
    starts = set()
    for window in preference.windows:
        start, end = window_span(window)
        starts.update(range(start, end - duration + 1, 15))
    return starts


def _validate_order(preferences: list[DevicePreference], devices: dict) -> list[dict]:
    """„Wykonaj po”: poprzednik pracuje jutro, nie ma pętli, a program zdąży przed „skończ najpóźniej o”.

    Urządzenie rusza 0–60 min po końcu poprzednika (jak suszarka po pralce w pliku). Sprawdzamy tylko
    włączone urządzenia, a poprawność samych przedziałów i programów jest już sprawdzona.
    """
    by_id = {preference.device_id: (index, preference) for index, preference in enumerate(preferences)}
    gap = AFTER_MAX_GAP_MIN
    errors = []
    ends_cache: dict[str, set[int]] = {}

    def root_start(device_id: str) -> int:
        """Początek najwcześniejszego przedziału pierwszego urządzenia w łańcuchu: od niego liczymy dobę."""
        preference = by_id[device_id][1]
        while preference.after_device_id is not None:
            preference = by_id[preference.after_device_id][1]
        return min(window_span(window)[0] for window in preference.windows)

    def deadline(device_id: str) -> int | None:
        finish_by = by_id[device_id][1].finish_by
        if finish_by is None:
            return None
        minutes = _minutes(finish_by)
        return minutes if minutes > root_start(device_id) else minutes + DAY_MINUTES

    def ends(device_id: str) -> set[int]:
        """Możliwe końce programu urządzenia z uwzględnieniem łańcucha poprzedników."""
        if device_id not in ends_cache:
            preference = by_id[device_id][1]
            duration = _program(preference, devices[device_id][1]).duration_min
            if preference.after_device_id is None:
                found = {start + duration for start in _starts(preference, duration)}
            else:
                latest = deadline(device_id)
                found = {
                    end + wait + duration
                    for end in ends(preference.after_device_id)
                    for wait in range(0, gap + 1, 15)
                    if latest is None or end + wait + duration <= latest
                }
            ends_cache[device_id] = found
        return ends_cache[device_id]

    for index, preference in enumerate(preferences):
        after = preference.after_device_id
        if not preference.enabled or after is None:
            continue
        device, programs = devices[preference.device_id]
        if not programs:
            errors.append(_error(index, "after_device_id", "Tylko urządzenie z programem może czekać na inne."))
            continue
        if after == preference.device_id:
            errors.append(_error(index, "after_device_id", "Urządzenie nie może czekać na samo siebie."))
            continue
        if after not in devices or not devices[after][1]:
            errors.append(_error(index, "after_device_id", "Wybierz urządzenie z programem."))
            continue
        if after not in by_id or not by_id[after][1].enabled:
            errors.append(_error(
                index, "after_device_id",
                f"{devices[after][0].name} nie pracuje jutro. Zaznacz je albo usuń „Wykonaj po”.",
            ))
            continue
        # Pętla: idąc po poprzednikach wracamy do tego samego urządzenia.
        seen, current = {preference.device_id}, after
        while current is not None and current in by_id and current not in seen:
            seen.add(current)
            current = by_id[current][1].after_device_id
        if current == preference.device_id:
            errors.append(_error(index, "after_device_id", "Urządzenia nie mogą czekać na siebie nawzajem."))
    if errors:
        return errors

    for index, preference in enumerate(preferences):
        after = preference.after_device_id
        if not preference.enabled or after is None or ends(preference.device_id):
            continue
        before = ends(after)
        if not before:
            continue  # poprzednik sam się nie mieści: błąd jest przy nim
        program = _program(preference, devices[preference.device_id][1])
        errors.append(_error(
            index, "finish_by",
            f"{devices[after][0].name} skończy się najwcześniej o {_clock_of(min(before))}, a {program.name} "
            f"trwa {_hours_text(program.duration_min)} – nie zdąży przed {preference.finish_by}.",
        ))
    return errors


def _clock_of(minutes: int) -> str:
    minutes %= DAY_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _error(index: int, field: str, message: str) -> dict:
    """Błąd pola w formacie walidacji FastAPI, żeby ekran pokazał go przy urządzeniu."""
    return {"loc": ["body", "devices", index, field], "msg": message, "type": "value_error"}

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from app.parsers.base import (
    KWH,
    TIMESTAMP_START,
    UNIT_ACTION,
    DevicesSummary,
    DocumentParser,
    FileImportError,
    ImportReport,
    ParsedEnergyFile,
)
from app.parsers.device_records import ActionRecord, DeviceRecord, ProgramRecord
from app.parsers.device_validation import SLOT, action_profile, validate_document


LOCAL_TIMEZONE = ZoneInfo("Europe/Warsaw")
QUARTER_HOUR = 15
MAX_LISTED_ERRORS = 5


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _optional_time(value: str | None) -> datetime | None:
    return _time(value) if value else None


def _clock(value: str | None):
    return datetime.strptime(value, "%H:%M").time() if value else None


def _invalid_file_message(errors: list[str]) -> str:
    listed = "; ".join(errors[:MAX_LISTED_ERRORS])
    more = f" …i {len(errors) - MAX_LISTED_ERRORS} więcej." if len(errors) > MAX_LISTED_ERRORS else ""
    return f"Plik urządzeń zawiera błędy ({len(errors)}): {listed}{more}"


class DevicesJsonParser(DocumentParser):
    """Plik urządzeń zgodny z docs/devices-file-format.md.

    Zwraca urządzenia z akcjami rozłożonymi na kwadranse (do zapisu w bazie) oraz sumę zużycia
    w kwadransach (do standardowej wyceny taryf, tak jak dla pliku CSV).
    """

    name = "devices"
    label = "Plik urządzeń smart home (JSON)"

    def detect(self, document: dict) -> bool:
        return "devices" in document and "energy_usage" in document

    def parse(self, document: dict) -> ParsedEnergyFile:
        # Profil użytkownika nie ma jeszcze mocy przyłącza, więc limit przyłącza (reguła 14) pomijamy.
        validation = validate_document(document, max_grid_kw=None)
        if not validation.is_valid:
            raise FileImportError(422, _invalid_file_message(validation.errors))

        devices = self._device_records(document)
        slots = self._slots_utc(devices)
        consumption = slots[slots > 0]
        data = self._consumption_series(consumption, document["period"])

        report = ImportReport(
            detected_format=self.name,
            format_label=self.label,
            rows_total=validation.actions_count,
            rows_imported=validation.actions_count,
            resolution_minutes=QUARTER_HOUR,
            unit=UNIT_ACTION,
            devices=DevicesSummary(
                devices_count=validation.devices_count,
                actions_count=validation.actions_count,
                categories=sorted(validation.categories),
                consumption_kwh=round(float(consumption.sum()), 2),
                pv_production_kwh=round(float(-slots[slots < 0].sum()), 2),
            ),
        )
        return ParsedEnergyFile(data=data, resolution_minutes=QUARTER_HOUR, report=report, devices=devices)

    @staticmethod
    def _device_records(document: dict) -> list[DeviceRecord]:
        """Zamienia poprawny plik na rekordy; energia akcji trafia na kwadranse według reguł formatu."""
        records, programs = {}, {}
        for device in document["devices"]:
            device_programs = device.get("programs", [])
            flexibility = device["flexibility"]
            window = flexibility.get("allowed_window", {})
            programs[device["device_id"]] = {program["program_id"]: program for program in device_programs}
            records[device["device_id"]] = DeviceRecord(
                device_id=device["device_id"],
                name=device["device_name"],
                device_type=device["device_type"],
                device_category=device["device_category"],
                flexibility_mode=flexibility["mode"],
                max_power_kw=device.get("max_power_kw"),
                allowed_window_from=_clock(window.get("from")),
                allowed_window_to=_clock(window.get("to")),
                max_shift_min=flexibility.get("max_shift_min"),
                programs=[
                    ProgramRecord(program["program_id"], program["program_name"], program["duration_min"],
                                  program["profile_kwh"])
                    for program in device_programs
                ],
            )

        for action in document["energy_usage"]:
            start, end = _time(action["action_start"]), _time(action["action_end"])
            device_id = action["device_id"]
            slots_kwh = action_profile(action, {"programs": programs[device_id]}, int((end - start) / SLOT))
            records[device_id].actions.append(ActionRecord(
                action_id=action["action_id"],
                start=start,
                end=end,
                energy_kwh=action["energy_kwh"],
                slots_kwh=slots_kwh,
                program_id=action.get("program_id"),
                plugged_in=_optional_time(action.get("plugged_in")),
                deadline=_optional_time(action.get("deadline")),
            ))
        return list(records.values())

    @staticmethod
    def _slots_utc(devices: list[DeviceRecord]) -> pd.Series:
        """Energia wszystkich akcji w kwadransach (UTC); ujemne wartości to produkcja PV."""
        starts, values = [], []
        for device in devices:
            for action in device.actions:
                start = action.start.astimezone(timezone.utc)
                for index, kwh in enumerate(action.slots_kwh):
                    starts.append(start + index * SLOT)
                    values.append(kwh)
        return pd.Series(values, index=pd.DatetimeIndex(starts, tz="UTC"), dtype=float)

    @staticmethod
    def _consumption_series(consumption: pd.Series, period: dict) -> pd.DataFrame:
        """Suma zużycia w każdym kwadransie okresu, w czasie lokalnym jak dane z licznika.

        Kwadrans bez akcji ma 0 kWh: w pliku zdarzeniowym brak akcji znaczy „nic nie pracowało”.
        """
        quarters = pd.date_range(
            _time(period["start"]).astimezone(timezone.utc),
            _time(period["end"]).astimezone(timezone.utc),
            freq=f"{QUARTER_HOUR}min",
            inclusive="left",
        )
        usage = consumption.groupby(level=0).sum().reindex(quarters, fill_value=0.0)
        return pd.DataFrame({
            TIMESTAMP_START: usage.index.tz_convert(LOCAL_TIMEZONE).tz_localize(None),
            KWH: usage.to_numpy(),
        })

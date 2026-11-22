from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import numpy as np
import pandas as pd
from fastapi import HTTPException

from app.parsers import (
    EXPORTED_KWH,
    HOURLY_RESOLUTION,
    KWH,
    TIMESTAMP_START,
    FileImportError,
    DeviceRecord,
    ParsedEnergyFile,
    parse_energy_file,
)
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers.devices import LOCAL_TIMEZONE
from app.providers.prices.base import expected_intervals


SLOTS_PER_DAY = 96
SLOT_MINUTES = 15
# Klucze wyników potrzebne tylko do przeliczania zakresów dat - nie wysyłamy ich do frontu.
INTERNAL_RESULT_KEYS = ("usage_15min",)
IMPORT_REPORT_KEY = "import_report"
ACTIONS_PER_DAY_KEY = "actions_per_day"


def public_results(results: dict | None) -> dict | None:
    if results is None:
        return None
    hidden = (*INTERNAL_RESULT_KEYS, IMPORT_REPORT_KEY, ACTIONS_PER_DAY_KEY)
    return {key: value for key, value in results.items() if key not in hidden}


def has_usage_series(results: dict) -> bool:
    return "usage_15min" in results


def source_resolution(results: dict) -> int | None:
    return results.get("statistics", {}).get("resolution_minutes", HOURLY_RESOLUTION)


class CalculationService:
    @staticmethod
    def format_hour_label(dt_obj):
        if dt_obj.minute == 0:
            new_hour = (dt_obj.hour - 1) % 24
            return f"{new_hour:02d}:00"
        return f"{dt_obj.hour:02d}:00"

    def summarize_file(self, file_obj) -> dict:
        return self.calculate_with_report(self.parse_file(file_obj))

    @staticmethod
    def parse_file(file_obj) -> ParsedEnergyFile:
        try:
            return parse_energy_file(file_obj)
        except FileImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc

    def calculate_with_report(self, parsed: ParsedEnergyFile) -> dict:
        results_dict = self.calculate(parsed)
        results_dict[IMPORT_REPORT_KEY] = parsed.report.to_dict()
        return results_dict

    @staticmethod
    def _quarter_hours(parsed: ParsedEnergyFile) -> pd.DataFrame:
        """Dzieli odczyty na kwadranse; odczyt godzinowy rozkłada równo na cztery."""
        data = parsed.data
        resolution = parsed.resolution_minutes
        slots_per_record = resolution // SLOT_MINUTES

        df_15min = data.loc[data.index.repeat(slots_per_record)].reset_index(drop=True)
        df_15min['Wartość kWh'] = df_15min[KWH] / slots_per_record
        exported = df_15min[EXPORTED_KWH] if EXPORTED_KWH in df_15min else 0.0
        df_15min['Oddanie kWh'] = exported / slots_per_record

        minute_offsets = np.tile(np.arange(0, resolution, SLOT_MINUTES), len(data))
        df_15min['Dokładny Czas'] = df_15min[TIMESTAMP_START] + pd.to_timedelta(minute_offsets, unit='m')
        return df_15min

    @classmethod
    def quarter_hour_readings(cls, parsed: ParsedEnergyFile) -> list[tuple[datetime, float, float]]:
        """Odczyty do zapisu w bazie: (początek kwadransu, pobór z sieci, oddanie do sieci)."""
        grouped = (
            cls._quarter_hours(parsed)
            .groupby('Dokładny Czas')[['Wartość kWh', 'Oddanie kWh']]
            .sum()
            .round(6)
        )
        return [
            (timestamp.to_pydatetime(), float(imported), float(exported))
            for timestamp, imported, exported in grouped.itertuples()
        ]

    def calculate(self, parsed: ParsedEnergyFile) -> dict:
        """Seria zużycia i statystyki pliku. Kosztów nie zapisujemy: liczy je przy odczycie silnik rachunku
        z bieżącego cennika (`tariff_definitions`)."""
        usage = self._build_usage_series(self._quarter_hours(parsed))
        actions_per_day = self._actions_per_day(parsed.devices) if parsed.devices is not None else None
        results_dict = self.summarize_usage(usage, {}, parsed.resolution_minutes, actions_per_day)
        if actions_per_day is None:
            results_dict["statistics"]["records_count"] = int(len(parsed.data))
        else:
            results_dict[ACTIONS_PER_DAY_KEY] = actions_per_day
        results_dict["usage_15min"] = usage
        return results_dict

    @staticmethod
    def usage_in_range(usage: dict, date_from: date, date_to: date) -> dict:
        start, end = date_from.isoformat(), date_to.isoformat()
        return {day: slots for day, slots in usage.items() if start <= day <= end}

    @staticmethod
    def _actions_per_day(devices: list[DeviceRecord]) -> dict[str, int]:
        counts = Counter(
            action.start.astimezone(LOCAL_TIMEZONE).date().isoformat()
            for device in devices
            for action in device.actions
        )
        return dict(sorted(counts.items()))

    @staticmethod
    def device_coverage(usages: list[dict]) -> dict[tuple[str, int], list[int]]:
        covering = defaultdict(list)
        for index, usage in enumerate(usages):
            for day, day_slots in usage.items():
                for slot, kwh in enumerate(day_slots):
                    if kwh is not None:
                        covering[(day, slot)].append(index)
        return covering

    @staticmethod
    def device_usage_series(covering: dict[tuple[str, int], list[int]], slot_rows) -> dict[str, list[float | None]]:
        """Seria „Wszystkich plików urządzeń”: kwadranse objęte którymkolwiek plikiem mają co najmniej 0 kWh.

        `slot_rows` to (dzień lokalny, kwadrans, pobór z sieci) z obowiązujących wersji urządzeń.
        """
        usage = {}
        for day, slot in covering:
            usage.setdefault(day, [None] * SLOTS_PER_DAY)[slot] = 0.0
        for day, slot, kwh in slot_rows:
            usage.setdefault(day, [None] * SLOTS_PER_DAY)[slot] = round(float(kwh), 6)
        return dict(sorted(usage.items()))

    @staticmethod
    def device_contributions(file_devices: list[set], covering: dict[tuple[str, int], list[int]]) -> list[dict]:
        """Dla każdego pliku: ile dni i kwadransów ma co najmniej jedno urządzenie nieprzykryte nowszym plikiem."""
        # Kwadranse z tym samym zestawem plików mają ten sam wynik; takich zestawów jest kilka.
        days_by_files = defaultdict(list)
        for (day, _), indices in covering.items():
            days_by_files[tuple(indices)].append(day)

        contributions = [{"days_used": set(), "slots_used": 0} for _ in file_devices]
        for indices, days in days_by_files.items():
            claimed = set()
            for index in reversed(indices):
                if file_devices[index] - claimed:
                    contributions[index]["days_used"].update(days)
                    contributions[index]["slots_used"] += len(days)
                if len(indices) > 1:
                    claimed |= file_devices[index]
        return [{**item, "days_used": len(item["days_used"])} for item in contributions]

    @staticmethod
    def merge_usage(sources: list[dict]) -> tuple[dict, list[dict]]:
        """Scala serie zużycia kilku plików w jedną.

        `sources` muszą być posortowane od najstarszego do najnowszego uploadu. Dla każdego
        kwadransu wygrywa pomiar z nowszego pliku; brak pomiaru w nowszym pliku nie kasuje
        wartości ze starszego, więc pliki wzajemnie uzupełniają luki. Pomiary z różnych plików
        nigdy się nie sumują - identyczne rekordy z dwóch plików liczą się raz.

        Zwraca scaloną serię i dla każdego źródła liczbę dni oraz kwadransów, które
        ostatecznie z niego pochodzą.
        """
        merged = {}
        owners = {}
        for index, source in enumerate(sources):
            for day, day_slots in source["usage_15min"].items():
                merged_slots = merged.setdefault(day, [None] * SLOTS_PER_DAY)
                day_owners = owners.setdefault(day, [None] * SLOTS_PER_DAY)
                for slot, kwh in enumerate(day_slots):
                    if kwh is not None:
                        merged_slots[slot] = kwh
                        day_owners[slot] = index

        contributions = [{"days_used": 0, "slots_used": 0} for _ in sources]
        for day_owners in owners.values():
            day_sources = {owner for owner in day_owners if owner is not None}
            for owner in day_sources:
                contributions[owner]["days_used"] += 1
                contributions[owner]["slots_used"] += day_owners.count(owner)

        return dict(sorted(merged.items())), contributions

    @staticmethod
    def _price_column(tariff: dict, df_15min: pd.DataFrame) -> pd.Series:
        prices_by_day = tariff["prices_by_day"]
        values = [
            (prices_by_day.get(day) or [None] * SLOTS_PER_DAY)[slot]
            for day, slot in zip(df_15min['date'], df_15min['slot'])
        ]
        return pd.Series(values, index=df_15min.index, dtype=float)

    @staticmethod
    def _to_records(df: pd.DataFrame) -> list[dict]:
        return df.astype(object).where(df.notna(), None).to_dict('records')

    @staticmethod
    def _build_usage_series(df_15min) -> dict[str, list[float | None]]:
        """Zużycie w postaci {"RRRR-MM-DD": [96 wartości kWh]}; None oznacza brak pomiaru w danym slocie."""
        timestamps = df_15min['Dokładny Czas']
        days = timestamps.dt.date.astype(str)
        slots = timestamps.dt.hour * (60 // SLOT_MINUTES) + timestamps.dt.minute // SLOT_MINUTES
        grouped = df_15min.groupby([days, slots])['Wartość kWh'].sum()

        usage = {}
        for (day, slot), kwh in grouped.items():
            usage.setdefault(day, [None] * SLOTS_PER_DAY)[int(slot)] = round(float(kwh), 6)
        # Dzień w środku pliku bez żadnego pomiaru też jest brakiem danych: zapisujemy go z samymi None,
        # żeby statystyki pokazały go jako niepełny.
        if usage:
            first, last = date.fromisoformat(min(usage)), date.fromisoformat(max(usage))
            for offset in range((last - first).days + 1):
                usage.setdefault((first + timedelta(days=offset)).isoformat(), [None] * SLOTS_PER_DAY)
        return dict(sorted(usage.items()))

    @staticmethod
    def _sum_energy_average_prices(grouped, sum_columns: list[str], price_columns: list[str]) -> pd.DataFrame:
        # Zużycie i koszt sumujemy w okresie, a cenę kWh uśredniamy (suma cen 4 kwadransów to nie cena godziny).
        return grouped[sum_columns].sum(min_count=1).join(grouped[price_columns].mean())

    @classmethod
    def summarize_usage(
        cls,
        usage: dict,
        slot_prices: dict,
        resolution_minutes: int | None = HOURLY_RESOLUTION,
        actions_per_day: dict[str, int] | None = None,
    ) -> dict:
        """Wykresy i statystyki serii {dzień: [96 kWh | None]}; `slot_prices` ({taryfa: {"prices_by_day": ...}})
        dodaje do wykresów kolumny price_<taryfa> i cost_<taryfa>."""
        data_source = EnergyDataFile.SOURCE_METER if actions_per_day is None else EnergyDataFile.SOURCE_DEVICES
        rows = [
            (day, slot, kwh)
            for day, day_slots in usage.items()
            for slot, kwh in enumerate(day_slots)
            if kwh is not None
        ]
        if not rows:
            return cls._empty_results(resolution_minutes, data_source)

        df_15min = pd.DataFrame(rows, columns=['date', 'slot', 'Wartość kWh'])
        df_15min['Dokładny Czas'] = pd.to_datetime(df_15min['date']) + pd.to_timedelta(
            df_15min['slot'] * SLOT_MINUTES, unit='m'
        )

        results_dict = {"total_usage_kwh": round(float(df_15min['Wartość kWh'].sum()), 2)}

        cost_columns = []
        price_columns = []

        for tariff_name, tariff in slot_prices.items():
            price_col_name = f'price_{tariff_name}'
            cost_col_name = f'cost_{tariff_name}'

            price_columns.append(price_col_name)
            cost_columns.append(cost_col_name)

            df_15min[price_col_name] = cls._price_column(tariff, df_15min)
            df_15min[cost_col_name] = df_15min['Wartość kWh'] * df_15min[price_col_name]

        columns_to_aggregate = ['Wartość kWh'] + cost_columns + price_columns

        df_15min['time_15m'] = df_15min['Dokładny Czas'].dt.strftime('%H:%M')
        data_15min = df_15min.groupby('time_15m')[columns_to_aggregate].mean().round(2).reset_index()
        data_15min = data_15min.rename(columns={'Wartość kWh': 'kwh', 'time_15m': 'time'})
        results_dict["chart_15min"] = cls._to_records(data_15min)
        
        # To samo co format_hour_label, ale wektorowo: przy pliku rocznym apply na 35 tys. wierszach był wolny.
        times = df_15min['Dokładny Czas'].dt
        hours = times.hour.where(times.minute != 0, (times.hour - 1) % 24)
        df_15min['hour'] = hours.astype(str).str.zfill(2) + ":00"
        
        daily_hourly_sum = cls._sum_energy_average_prices(
            df_15min.groupby(['date', 'hour']), ['Wartość kWh'] + cost_columns, price_columns
        ).reset_index()
        
        hourly_data = daily_hourly_sum.groupby('hour')[columns_to_aggregate].mean().round(2).reset_index()
        hourly_data = hourly_data.rename(columns={'Wartość kWh': 'kwh'})
        results_dict["chart_hourly"] = cls._to_records(hourly_data)

        daily_data = cls._sum_energy_average_prices(
            df_15min.groupby('date'), ['Wartość kWh'] + cost_columns, price_columns
        ).round(2).reset_index()
        daily_data = daily_data.rename(columns={'Wartość kWh': 'kwh'})
        results_dict["chart_daily"] = cls._to_records(daily_data)
        
        first_date = df_15min['date'].min()
        last_date = df_15min['date'].max()
        
        # Doba ze zmianą czasu na letni ma 92 kwadranse; 25-godzinna mieści się w 96 slotach.
        # Dzień bez żadnego pomiaru (same None) też jest niepełny.
        incomplete_days = [
            day
            for day, day_slots in usage.items()
            if sum(kwh is not None for kwh in day_slots)
            < min(expected_intervals(date.fromisoformat(day), SLOT_MINUTES), SLOTS_PER_DAY)
        ]

        if actions_per_day is not None:
            records_count = sum(actions_per_day.get(day, 0) for day in usage)
        elif resolution_minutes:
            records_count = int(len(df_15min)) // (resolution_minutes // SLOT_MINUTES)
        else:
            records_count = None

        results_dict["statistics"] = {
            "records_count": records_count,
            "resolution_minutes": resolution_minutes,
            "data_source": data_source,
            "days_analyzed": int(df_15min['date'].nunique()),
            "data_start": first_date,
            "data_end": last_date,
            "incomplete_days": incomplete_days,
            "has_missing_data": len(incomplete_days) > 0
        }

        return results_dict

    @staticmethod
    def _empty_results(resolution_minutes: int | None, data_source: str) -> dict:
        return {
            "total_usage_kwh": 0.0,
            "chart_15min": [],
            "chart_hourly": [],
            "chart_daily": [],
            "statistics": {
                "records_count": 0,
                "resolution_minutes": resolution_minutes,
                "data_source": data_source,
                "days_analyzed": 0,
                "data_start": None,
                "data_end": None,
                "incomplete_days": [],
                "has_missing_data": False,
            },
        }
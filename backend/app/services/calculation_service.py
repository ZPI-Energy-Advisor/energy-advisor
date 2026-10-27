from collections import Counter
from datetime import date
from typing import Mapping

import numpy as np
import pandas as pd
from fastapi import HTTPException

from app.parsers import (
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
from app.repositories.tariff_repository import TariffRepository
from app.services.pricing_strategies import (
    SLOT_MINUTES,
    SLOTS_PER_DAY,
    FixedRatePricing,
    TariffPricingStrategy,
)


# Klucze wyników potrzebne tylko do przeliczania zakresów dat - nie wysyłamy ich do frontu.
INTERNAL_RESULT_KEYS = ("usage_15min", "slot_prices")
IMPORT_REPORT_KEY = "import_report"
ACTIONS_PER_DAY_KEY = "actions_per_day"


def public_results(results: dict | None) -> dict | None:
    if results is None:
        return None
    hidden = (*INTERNAL_RESULT_KEYS, IMPORT_REPORT_KEY, ACTIONS_PER_DAY_KEY)
    return {key: value for key, value in results.items() if key not in hidden}


def has_usage_series(results: dict) -> bool:
    return all(key in results for key in INTERNAL_RESULT_KEYS)


def source_resolution(results: dict) -> int | None:
    return results.get("statistics", {}).get("resolution_minutes", HOURLY_RESOLUTION)


class CalculationService:
    def __init__(
        self,
        tariff_repository: TariffRepository,
        pricing_strategies: Mapping[str, TariffPricingStrategy] | None = None,
    ):
        self.tariff_repository = tariff_repository
        self.default_strategy = FixedRatePricing(tariff_repository)
        self.pricing_strategies = dict(pricing_strategies or {})

    def _strategy_for(self, tariff) -> TariffPricingStrategy:
        return self.pricing_strategies.get(tariff.type, self.default_strategy)

    @staticmethod
    def format_hour_label(dt_obj):
        if dt_obj.minute == 0:
            new_hour = (dt_obj.hour - 1) % 24
            return f"{new_hour:02d}:00"
        return f"{dt_obj.hour:02d}:00"


    def calculate_all_tariffs(self, file_obj) -> dict:
        return self.calculate_with_report(self.parse_file(file_obj))

    @staticmethod
    def parse_file(file_obj) -> ParsedEnergyFile:
        try:
            return parse_energy_file(file_obj)
        except FileImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    def calculate_with_report(self, parsed: ParsedEnergyFile) -> dict:
        results_dict = self.calculate(parsed)
        results_dict[IMPORT_REPORT_KEY] = parsed.report.to_dict()
        return results_dict

    def calculate(self, parsed: ParsedEnergyFile) -> dict:
        data = parsed.data
        resolution = parsed.resolution_minutes
        slots_per_record = resolution // SLOT_MINUTES

        df_15min = data.loc[data.index.repeat(slots_per_record)].reset_index(drop=True)
        df_15min['Wartość kWh'] = df_15min[KWH] / slots_per_record

        minute_offsets = np.tile(np.arange(0, resolution, SLOT_MINUTES), len(data))
        df_15min['Dokładny Czas'] = df_15min[TIMESTAMP_START] + pd.to_timedelta(minute_offsets, unit='m')

        tariffs = self.tariff_repository.get_all()
        if not tariffs:
            raise HTTPException(status_code=500, detail="Brak taryf w bazie danych!")

        usage = self._build_usage_series(df_15min)
        days = [date.fromisoformat(day) for day in usage]

        # Ceny zapisujemy razem z wynikami, żeby przeliczenie zakresu dawało te same
        # kwoty co przy imporcie, nawet jeśli cennik w bazie później się zmieni.
        slot_prices = {
            tariff.name: self._strategy_for(tariff).slot_prices(tariff, days)
            for tariff in tariffs
        }

        actions_per_day = self._actions_per_day(parsed.devices) if parsed.devices is not None else None
        results_dict = self.summarize_usage(usage, slot_prices, resolution, actions_per_day)
        if actions_per_day is None:
            results_dict["statistics"]["records_count"] = int(len(data))
        else:
            results_dict[ACTIONS_PER_DAY_KEY] = actions_per_day
        results_dict["usage_15min"] = usage
        results_dict["slot_prices"] = slot_prices
        return results_dict

    @classmethod
    def calculate_for_range(cls, results: dict, date_from: date, date_to: date) -> dict:
        """Przelicza wykresy, sumy i statystyki dla dni z przedziału [date_from, date_to] (oba włącznie)."""
        start, end = date_from.isoformat(), date_to.isoformat()
        usage = {day: slots for day, slots in results["usage_15min"].items() if start <= day <= end}
        return cls.summarize_usage(
            usage, results["slot_prices"], source_resolution(results), results.get(ACTIONS_PER_DAY_KEY)
        )

    @staticmethod
    def _actions_per_day(devices: list[DeviceRecord]) -> dict[str, int]:
        counts = Counter(
            action.start.astimezone(LOCAL_TIMEZONE).date().isoformat()
            for device in devices
            for action in device.actions
        )
        return dict(sorted(counts.items()))

    @staticmethod
    def merge_actions_per_day(sources: list[dict]) -> dict[str, int]:
        """Doba należy do najnowszego pliku, który ją obejmuje - jak jego kwadranse w merge_usage."""
        merged = {}
        for source in sources:
            actions = source.get(ACTIONS_PER_DAY_KEY, {})
            for day in source["usage_15min"]:
                merged[day] = actions.get(day, 0)
        return dict(sorted(merged.items()))

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
    def merge_slot_prices(sources: list[dict]) -> dict:
        """Scala cenniki kilku importów (posortowanych od najstarszego).

        Ceny zależne od pory dnia bierzemy z najnowszego importu. Ceny dzienne (taryfa
        dynamiczna) łączymy po dniach - nowszy import nadpisuje starszy tylko tam, gdzie ma cenę.
        """
        latest = sources[-1]
        merged = {}
        for tariff_name, tariff in latest.items():
            if "prices_by_day" not in tariff:
                merged[tariff_name] = tariff
                continue

            prices_by_day = {}
            for source in sources:
                source_days = source.get(tariff_name, {}).get("prices_by_day", {})
                for day, day_prices in source_days.items():
                    current = prices_by_day.get(day, [None] * SLOTS_PER_DAY)
                    prices_by_day[day] = [
                        new if new is not None else old for old, new in zip(current, day_prices)
                    ]
            merged[tariff_name] = {**tariff, "prices_by_day": dict(sorted(prices_by_day.items()))}
        return merged

    @staticmethod
    def _price_column(tariff: dict, df_15min: pd.DataFrame) -> pd.Series:
        if "prices_by_day" in tariff:
            prices_by_day = tariff["prices_by_day"]
            values = [
                (prices_by_day.get(day) or [None] * SLOTS_PER_DAY)[slot]
                for day, slot in zip(df_15min['date'], df_15min['slot'])
            ]
            return pd.Series(values, index=df_15min.index, dtype=float)
        return pd.Series(np.asarray(tariff["prices"])[df_15min['slot']], index=df_15min.index, dtype=float)

    @staticmethod
    def _tariff_cost(tariff: dict, df_15min: pd.DataFrame, price_col: str, cost_col: str, total_usage: float) -> dict:
        if "prices_by_day" not in tariff:
            return {"estimated_cost_pln": round(float(df_15min[cost_col].sum()), 2)}

        priced = df_15min[price_col].notna()
        covered_usage = float(df_15min.loc[priced, 'Wartość kWh'].sum())
        covered_cost = float(df_15min.loc[priced, cost_col].sum())

        if not priced.any():
            estimated_cost = None
        elif not priced.all() and covered_usage > 0:
            estimated_cost = round(covered_cost * total_usage / covered_usage, 2)
        else:
            estimated_cost = round(covered_cost, 2)

        return {
            "estimated_cost_pln": estimated_cost,
            "price_coverage": round(float(priced.mean()), 4),
            "missing_price_intervals": int((~priced).sum()),
        }

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
        return dict(sorted(usage.items()))

    @classmethod
    def summarize_usage(
        cls,
        usage: dict,
        slot_prices: dict,
        resolution_minutes: int | None = HOURLY_RESOLUTION,
        actions_per_day: dict[str, int] | None = None,
    ) -> dict:
        data_source = EnergyDataFile.SOURCE_METER if actions_per_day is None else EnergyDataFile.SOURCE_DEVICES
        rows = [
            (day, slot, kwh)
            for day, day_slots in usage.items()
            for slot, kwh in enumerate(day_slots)
            if kwh is not None
        ]
        if not rows:
            return cls._empty_results(slot_prices, resolution_minutes, data_source)

        df_15min = pd.DataFrame(rows, columns=['date', 'slot', 'Wartość kWh'])
        df_15min['Dokładny Czas'] = pd.to_datetime(df_15min['date']) + pd.to_timedelta(
            df_15min['slot'] * SLOT_MINUTES, unit='m'
        )

        results_dict = {"tariffs": {}}
        total_usage = float(df_15min['Wartość kWh'].sum())

        cost_columns = []
        price_columns = []

        for tariff_name, tariff in slot_prices.items():
            price_col_name = f'price_{tariff_name}'
            cost_col_name = f'cost_{tariff_name}'

            price_columns.append(price_col_name)
            cost_columns.append(cost_col_name)

            df_15min[price_col_name] = cls._price_column(tariff, df_15min)
            df_15min[cost_col_name] = df_15min['Wartość kWh'] * df_15min[price_col_name]

            results_dict["tariffs"][tariff_name] = {
                "type": tariff["type"],
                "total_usage_kwh": round(total_usage, 2),
                **cls._tariff_cost(tariff, df_15min, price_col_name, cost_col_name, total_usage),
            }

        columns_to_aggregate = ['Wartość kWh'] + cost_columns + price_columns

        df_15min['time_15m'] = df_15min['Dokładny Czas'].dt.strftime('%H:%M')
        data_15min = df_15min.groupby('time_15m')[columns_to_aggregate].mean().round(2).reset_index()
        data_15min = data_15min.rename(columns={'Wartość kWh': 'kwh', 'time_15m': 'time'})
        results_dict["chart_15min"] = cls._to_records(data_15min)
        
        df_15min['hour'] = df_15min['Dokładny Czas'].apply(cls.format_hour_label)
        
        daily_hourly_sum = df_15min.groupby(['date', 'hour'])[columns_to_aggregate].sum(min_count=1).reset_index()
        
        hourly_data = daily_hourly_sum.groupby('hour')[columns_to_aggregate].mean().round(2).reset_index()
        hourly_data = hourly_data.rename(columns={'Wartość kWh': 'kwh'})
        results_dict["chart_hourly"] = cls._to_records(hourly_data)

        daily_data = df_15min.groupby('date')[columns_to_aggregate].sum(min_count=1).round(2).reset_index()
        daily_data = daily_data.rename(columns={'Wartość kWh': 'kwh'})
        results_dict["chart_daily"] = cls._to_records(daily_data)
        
        first_date = df_15min['date'].min()
        last_date = df_15min['date'].max()
        
        daily_counts = df_15min.groupby('date').size()
        incomplete_days = daily_counts[daily_counts < SLOTS_PER_DAY].index.tolist()

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
    def _empty_results(slot_prices: dict, resolution_minutes: int | None, data_source: str) -> dict:
        return {
            "tariffs": {
                tariff_name: {"type": tariff["type"], "total_usage_kwh": 0.0, "estimated_cost_pln": 0.0}
                for tariff_name, tariff in slot_prices.items()
            },
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
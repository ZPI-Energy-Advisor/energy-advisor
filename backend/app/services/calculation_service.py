from datetime import date
from typing import Mapping

import numpy as np
import pandas as pd
from fastapi import HTTPException

from app.repositories.tariff_repository import TariffRepository
from app.services.pricing_strategies import (
    SLOT_MINUTES,
    SLOTS_PER_DAY,
    FixedRatePricing,
    TariffPricingStrategy,
)


YEAR_FIRST_DATE = r'^\d{4}-\d{1,2}-\d{1,2}(?:[ T]|$)'
DAY_OR_MONTH_FIRST_DATE = r'^(\d{1,2})[./-](\d{1,2})[./-]\d{4}(?:\s|$)'
EXCEL_SERIAL_DATE = r'^\d+(?:\.\d+)?$'
MIDNIGHT_24 = r'(?<=\s)24:00(?=(?::00)?$)'

# Klucze wyników potrzebne tylko do przeliczania zakresów dat - nie wysyłamy ich do frontu.
INTERNAL_RESULT_KEYS = ("usage_15min", "slot_prices")


def public_results(results: dict | None) -> dict | None:
    if results is None:
        return None
    return {key: value for key, value in results.items() if key not in INTERNAL_RESULT_KEYS}


def has_usage_series(results: dict) -> bool:
    return all(key in results for key in INTERNAL_RESULT_KEYS)


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
        try:
            file_obj.seek(0)
            df = pd.read_csv(file_obj, sep=';', encoding='utf-8')
        except UnicodeDecodeError:
            file_obj.seek(0)
            df = pd.read_csv(file_obj, sep=';', encoding='windows-1250')
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Błąd odczytu pliku: {e}")
            
        df.columns = df.columns.str.strip()

        if "Data i godzina" in df.columns and "Wartosc[kWh/kvar]" in df.columns:
            df = df.rename(columns={
                "Data i godzina": "Data",
                "Wartosc[kWh/kvar]": "Wartość kWh",
                "Rodzaj energii": "Rodzaj"
            })
        elif "Data" not in df.columns or "Wartość kWh" not in df.columns:
            raise HTTPException(status_code=422, detail="Nierozpoznany format pliku. Brak wymaganych kolumn.")

        df = df.dropna(subset=['Wartość kWh', 'Data', 'Rodzaj'])
        df['Rodzaj'] = df['Rodzaj'].astype(str).str.strip().str.lower()
        
        df['Wartość kWh'] = df['Wartość kWh'].astype(str).str.replace(',', '.', regex=False)
        df['Wartość kWh'] = pd.to_numeric(df['Wartość kWh'], errors='coerce')
        df = df.dropna(subset=['Wartość kWh'])

        df = df[df['Rodzaj'].str.contains('pobór|pobor|pobrana', na=False)].copy()

        if df.empty:
            raise HTTPException(status_code=400, detail="Plik zawiera tylko dane o oddaniu energii (brak poboru) lub dane są puste.")

        # Odczyt "24:00" to koniec doby - parsujemy go jako 00:00 i przesuwamy na następny dzień.
        df['Data'] = df['Data'].astype(str).str.strip()
        mask_24 = df['Data'].str.contains(MIDNIGHT_24, regex=True)
        df['Data'] = df['Data'].str.replace(MIDNIGHT_24, '00:00', regex=True)

        df['Data'] = self._parse_dates(df['Data'])
        if df['Data'].isna().all():
            raise HTTPException(
                status_code=422,
                detail="Nie rozpoznano formatu dat w pliku. Obsługiwane formaty: RRRR-MM-DD GG:MM, "
                "DD.MM.RRRR GG:MM (także z / lub -) oraz daty liczbowe z Excela.",
            )
        df = df.dropna(subset=['Data'])

        df.loc[mask_24, 'Data'] = df.loc[mask_24, 'Data'] + pd.Timedelta(days=1)

        df_15min = df.loc[df.index.repeat(4)].reset_index(drop=True)
        df_15min['Wartość kWh'] = df_15min['Wartość kWh'] / 4.0

        base_timestamps = df_15min['Data']

        minute_offsets = np.tile([-60, -45, -30, -15], len(df))
        df_15min['Dokładny Czas'] = base_timestamps + pd.to_timedelta(minute_offsets, unit='m')

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

        results_dict = self.summarize_usage(usage, slot_prices)
        results_dict["statistics"]["records_count"] = int(len(df))
        results_dict["usage_15min"] = usage
        results_dict["slot_prices"] = slot_prices
        return results_dict

    @staticmethod
    def _parse_dates(values: pd.Series) -> pd.Series:
        """Rozpoznaje format każdej daty po jej zapisie, a nie po nazwach kolumn pliku.

        - RRRR-MM-DD (np. plik zapisany ponownie w Excelu) - zawsze rok, miesiąc, dzień,
        - DD.MM.RRRR, DD/MM/RRRR, DD-MM-RRRR - kolejność dnia i miesiąca ustalana dla całego
          pliku: jeśli gdzieś pierwsza liczba > 12, to dzień jest pierwszy; jeśli tylko druga
          liczba bywa > 12, to plik jest w układzie MM/DD; gdy nie da się tego rozstrzygnąć,
          przyjmujemy polski układ z dniem na początku,
        - liczby - numer seryjny daty z Excela.

        Wartości w nierozpoznanym formacie dostają NaT.
        """
        parsed = pd.Series(pd.NaT, index=values.index, dtype='datetime64[ns]')

        year_first = values.str.match(YEAR_FIRST_DATE)
        if year_first.any():
            parsed[year_first] = pd.to_datetime(
                values[year_first], format='mixed', yearfirst=True, dayfirst=False, errors='coerce'
            )

        day_or_month_first = values.str.match(DAY_OR_MONTH_FIRST_DATE)
        if day_or_month_first.any():
            parts = values[day_or_month_first].str.extract(DAY_OR_MONTH_FIRST_DATE).astype(int)
            month_first = not (parts[0] > 12).any() and (parts[1] > 12).any()
            parsed[day_or_month_first] = pd.to_datetime(
                values[day_or_month_first], format='mixed', dayfirst=not month_first, errors='coerce'
            )

        excel_serial = values.str.match(EXCEL_SERIAL_DATE)
        if excel_serial.any():
            parsed[excel_serial] = pd.to_datetime(
                pd.to_numeric(values[excel_serial]), unit='D', origin='1899-12-30'
            )

        return parsed

    @classmethod
    def calculate_for_range(cls, results: dict, date_from: date, date_to: date) -> dict:
        """Przelicza wykresy, sumy i statystyki dla dni z przedziału [date_from, date_to] (oba włącznie)."""
        start, end = date_from.isoformat(), date_to.isoformat()
        usage = {day: slots for day, slots in results["usage_15min"].items() if start <= day <= end}
        return cls.summarize_usage(usage, results["slot_prices"])

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
    def summarize_usage(cls, usage: dict, slot_prices: dict) -> dict:
        rows = [
            (day, slot, kwh)
            for day, day_slots in usage.items()
            for slot, kwh in enumerate(day_slots)
            if kwh is not None
        ]
        if not rows:
            return cls._empty_results(slot_prices)

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

        results_dict["statistics"] = {
            # Dane źródłowe są godzinowe, więc jeden rekord to 4 sloty 15-minutowe.
            "records_count": int(len(df_15min)) // 4,
            "days_analyzed": int(df_15min['date'].nunique()),
            "data_start": first_date,
            "data_end": last_date,
            "incomplete_days": incomplete_days,
            "has_missing_data": len(incomplete_days) > 0
        }

        return results_dict

    @staticmethod
    def _empty_results(slot_prices: dict) -> dict:
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
                "days_analyzed": 0,
                "data_start": None,
                "data_end": None,
                "incomplete_days": [],
                "has_missing_data": False,
            },
        }
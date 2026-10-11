from datetime import date, time

import numpy as np
import pandas as pd
from fastapi import HTTPException

from app.repositories.tariff_repository import TariffRepository


SLOTS_PER_DAY = 96
SLOT_MINUTES = 15

# Klucze wyników potrzebne tylko do przeliczania zakresów dat - nie wysyłamy ich do frontu.
INTERNAL_RESULT_KEYS = ("usage_15min", "slot_prices")


def public_results(results: dict | None) -> dict | None:
    if results is None:
        return None
    return {key: value for key, value in results.items() if key not in INTERNAL_RESULT_KEYS}


def has_usage_series(results: dict) -> bool:
    return all(key in results for key in INTERNAL_RESULT_KEYS)


class CalculationService:
    def __init__(self, tariff_repository: TariffRepository):
        self.tariff_repository = tariff_repository

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
            is_day_first = True
        elif "Data" in df.columns and "Wartość kWh" in df.columns:
            is_day_first = False 
        else:
            raise HTTPException(status_code=422, detail="Nierozpoznany format pliku. Brak wymaganych kolumn.")

        df = df.dropna(subset=['Wartość kWh', 'Data', 'Rodzaj'])
        df['Rodzaj'] = df['Rodzaj'].astype(str).str.strip().str.lower()
        
        df['Wartość kWh'] = df['Wartość kWh'].astype(str).str.replace(',', '.', regex=False)
        df['Wartość kWh'] = pd.to_numeric(df['Wartość kWh'], errors='coerce')
        df = df.dropna(subset=['Wartość kWh'])

        df = df[df['Rodzaj'].str.contains('pobór|pobor|pobrana', na=False)].copy()

        if df.empty:
            raise HTTPException(status_code=400, detail="Plik zawiera tylko dane o oddaniu energii (brak poboru) lub dane są puste.")

        mask_24 = df['Data'].astype(str).str.contains('24:00')
        df['Data'] = df['Data'].astype(str).str.strip().str.replace('24:00', '00:00')

        is_numeric = df['Data'].str.match(r'^\d+(\.\d+)?$')
        
        text_dates = pd.to_datetime(df.loc[~is_numeric, 'Data'], format='mixed', dayfirst=is_day_first, errors='coerce')
        numeric_dates = pd.to_datetime(pd.to_numeric(df.loc[is_numeric, 'Data']), unit='D', origin='1899-12-30')
        
        df['Data'] = pd.concat([text_dates, numeric_dates]).sort_index()
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

        # Ceny zapisujemy razem z wynikami, żeby przeliczenie zakresu dawało te same
        # kwoty co przy imporcie, nawet jeśli cennik w bazie później się zmieni.
        slot_prices = {
            tariff.name: {
                "type": tariff.type,
                "prices": self._slot_prices(self.tariff_repository.get_rates_for_tariff(tariff.id)),
            }
            for tariff in tariffs
        }

        usage = self._build_usage_series(df_15min)

        results_dict = self.summarize_usage(usage, slot_prices)
        results_dict["statistics"]["records_count"] = int(len(df))
        results_dict["usage_15min"] = usage
        results_dict["slot_prices"] = slot_prices
        return results_dict

    @classmethod
    def calculate_for_range(cls, results: dict, date_from: date, date_to: date) -> dict:
        """Przelicza wykresy, sumy i statystyki dla dni z przedziału [date_from, date_to] (oba włącznie)."""
        start, end = date_from.isoformat(), date_to.isoformat()
        usage = {day: slots for day, slots in results["usage_15min"].items() if start <= day <= end}
        return cls.summarize_usage(usage, results["slot_prices"])

    @staticmethod
    def _slot_prices(rates) -> list[float]:
        def get_price(slot_time):
            for rate in rates:
                if rate.time_start <= slot_time <= rate.time_end:
                    return float(rate.price_per_kwh)
            return 0.0

        return [
            get_price(time(slot * SLOT_MINUTES // 60, slot * SLOT_MINUTES % 60))
            for slot in range(SLOTS_PER_DAY)
        ]

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

            df_15min[price_col_name] = np.asarray(tariff["prices"])[df_15min['slot']]
            df_15min[cost_col_name] = df_15min['Wartość kWh'] * df_15min[price_col_name]

            total_cost = float(df_15min[cost_col_name].sum())

            results_dict["tariffs"][tariff_name] = {
                "type": tariff["type"],
                "total_usage_kwh": round(total_usage, 2),
                "estimated_cost_pln": round(total_cost, 2)
            }

        columns_to_aggregate = ['Wartość kWh'] + cost_columns + price_columns

        df_15min['time_15m'] = df_15min['Dokładny Czas'].dt.strftime('%H:%M')
        data_15min = df_15min.groupby('time_15m')[columns_to_aggregate].mean().round(2).reset_index()
        data_15min = data_15min.rename(columns={'Wartość kWh': 'kwh', 'time_15m': 'time'})
        results_dict["chart_15min"] = data_15min.to_dict('records')
        
        df_15min['hour'] = df_15min['Dokładny Czas'].apply(cls.format_hour_label)
        
        daily_hourly_sum = df_15min.groupby(['date', 'hour'])[columns_to_aggregate].sum().reset_index()
        
        hourly_data = daily_hourly_sum.groupby('hour')[columns_to_aggregate].mean().round(2).reset_index()
        hourly_data = hourly_data.rename(columns={'Wartość kWh': 'kwh'})
        results_dict["chart_hourly"] = hourly_data.to_dict('records')

        daily_data = df_15min.groupby('date')[columns_to_aggregate].sum().round(2).reset_index()
        daily_data = daily_data.rename(columns={'Wartość kWh': 'kwh'})
        results_dict["chart_daily"] = daily_data.to_dict('records')
        
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
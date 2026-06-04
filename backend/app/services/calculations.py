import pandas as pd
import numpy as np
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.models import Tariff, TariffRate

REQUIRED_COLUMNS = {"Data", "Wartość kWh", "Rodzaj"}

def calculate_all_tariffs(file_obj, db: Session) -> dict:
    try:
        df = pd.read_csv(file_obj, sep=';', encoding='utf-8')
        df.columns = df.columns.str.strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Błąd odczytu pliku: {e}")
        
    if not REQUIRED_COLUMNS.issubset(set(df.columns)):
        raise HTTPException(status_code=422, detail="Brak wymaganych kolumn (Data, Wartość kWh, Rodzaj)")


    df['Rodzaj'] = df['Rodzaj'].astype(str).str.strip().str.lower()
    df['Wartość kWh'] = df['Wartość kWh'].astype(str).str.replace(',', '.').astype(float)
    df = df[df['Rodzaj'].str.contains('pobór|pobor', na=False)].copy()

    df['Data'] = df['Data'].str.strip().str.replace('24:00', '23:59')
    df['Data'] = pd.to_datetime(df['Data'], format='%Y-%m-%d %H:%M')

    df_15min = df.loc[df.index.repeat(4)].reset_index(drop=True)
    df_15min['Wartość kWh'] = df_15min['Wartość kWh'] / 4.0
    
    base_timestamps = df_15min['Data']
    minute_offsets = np.tile([-45, -30, -15, 0], len(df))
    df_15min['Dokładny Czas'] = base_timestamps + pd.to_timedelta(minute_offsets, unit='m')
    df_15min['Czas_Baza'] = df_15min['Dokładny Czas'].dt.time

    tariffs = db.query(Tariff).all()
    if not tariffs:
        raise HTTPException(status_code=500, detail="Brak taryf w bazie danych! Uruchom seed.py")

    results_dict = {"tariffs": {}}
    total_usage = float(df_15min['Wartość kWh'].sum())

    for tariff in tariffs:
        rates = db.query(TariffRate).filter(TariffRate.tariff_id == tariff.id).all()
        
        def get_price(row_time):
            for rate in rates:
                if rate.time_start <= row_time <= rate.time_end:
                    return float(rate.price_per_kwh)
            return 0.0

        df_15min[f'Cena_{tariff.name}'] = df_15min['Czas_Baza'].apply(get_price)
        df_15min[f'Koszt_{tariff.name}'] = df_15min['Wartość kWh'] * df_15min[f'Cena_{tariff.name}']
        
        total_cost = float(df_15min[f'Koszt_{tariff.name}'].sum())

        results_dict["tariffs"][tariff.name] = {
            "type": tariff.type,
            "total_usage_kwh": round(total_usage, 2),
            "estimated_cost_pln": round(total_cost, 2)
        }

    df_15min['date'] = df_15min['Dokładny Czas'].dt.date.astype(str)
    daily_data = df_15min.groupby('date')['Wartość kWh'].sum().round(2).reset_index()
    daily_data = daily_data.rename(columns={'Wartość kWh': 'kwh'})
    results_dict["chart_daily"] = daily_data.to_dict('records')
    
    results_dict["statistics"] = {
        "days_analyzed": int(df_15min['date'].nunique())
    }

    return results_dict
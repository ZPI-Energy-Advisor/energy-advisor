import pandas as pd
import numpy as np
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.models import Tariff, TariffRate
    
def format_hour_label(dt_obj):
    if dt_obj.minute == 0:
        new_hour = (dt_obj.hour - 1) % 24
        return f"{new_hour:02d}:00"
    return f"{dt_obj.hour:02d}:00"

def calculate_all_tariffs(file_obj, db: Session) -> dict:
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
        date_format = '%d.%m.%Y %H:%M'
    elif "Data" in df.columns and "Wartość kWh" in df.columns:
        date_format = '%Y-%m-%d %H:%M'
    else:
        raise HTTPException(status_code=422, detail="Nierozpoznany format pliku. Brak wymaganych kolumn.")

    df['Rodzaj'] = df['Rodzaj'].astype(str).str.strip().str.lower()
    df['Wartość kWh'] = df['Wartość kWh'].astype(str).str.replace(',', '.').astype(float)
    df = df[df['Rodzaj'].str.contains('pobór|pobor|pobrana', na=False)].copy()

    df['Data'] = df['Data'].str.strip().str.replace('24:00', '23:59')
    df['Data'] = pd.to_datetime(df['Data'], format=date_format)

    mask_midnight = df['Data'].dt.time == pd.to_datetime('00:00:00').time()
    df.loc[mask_midnight, 'Data'] = df.loc[mask_midnight, 'Data'] - pd.Timedelta(minutes=1)
 
    df_15min = df.loc[df.index.repeat(4)].reset_index(drop=True)
    df_15min['Wartość kWh'] = df_15min['Wartość kWh'] / 4.0
    
    base_timestamps = df_15min['Data']
    minute_offsets = np.tile([-45, -30, -15, 0], len(df))
    df_15min['Dokładny Czas'] = base_timestamps + pd.to_timedelta(minute_offsets, unit='m')
    df_15min['Czas_Baza'] = df_15min['Dokładny Czas'].dt.time

    tariffs = db.query(Tariff).all()
    if not tariffs:
        raise HTTPException(status_code=500, detail="Brak taryf w bazie danych!")

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

    df_15min['hour'] = df_15min['Dokładny Czas'].apply(format_hour_label)
    hourly_data = df_15min.groupby('hour')['Wartość kWh'].sum().round(2).reset_index()
    hourly_data = hourly_data.rename(columns={'Wartość kWh': 'kwh'})
    results_dict["chart_hourly"] = hourly_data.to_dict('records')

    df_15min['date'] = df_15min['Dokładny Czas'].dt.date.astype(str)
    daily_data = df_15min.groupby('date')['Wartość kWh'].sum().round(2).reset_index()
    daily_data = daily_data.rename(columns={'Wartość kWh': 'kwh'})
    results_dict["chart_daily"] = daily_data.to_dict('records')
     
    first_date = df_15min['date'].min()
    last_date = df_15min['date'].max()
    
    results_dict["statistics"] = {
        "days_analyzed": int(df_15min['date'].nunique()),
        "data_start": first_date,
        "data_end": last_date
    }

    return results_dict
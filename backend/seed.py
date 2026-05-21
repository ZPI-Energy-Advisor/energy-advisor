from app.database import SessionLocal
from app.models.models import Tariff, TariffRate
from datetime import time, datetime, timedelta

def seed_tariffs():
    db = SessionLocal()
    
    if db.query(Tariff).first():
        print("Baza ma już taryfy. Przerywam seedowanie.")
        db.close()
        return

    print("Rozpoczynam zasilanie bazy taryfami (interwały 15-minutowe)...")

    g11 = Tariff(name="G11", type="stala", description="Taryfa jednostrefowa - stała cena przez całą dobę.")
    db.add(g11)
    db.commit() 
    db.refresh(g11)
    db.add(TariffRate(tariff_id=g11.id, time_start=time(0, 0), time_end=time(23, 59, 59), price_per_kwh=1.15))

    g12 = Tariff(name="G12", type="strefowa", description="Taryfa dwustrefowa - tańszy prąd w nocy i wczesnym popołudniem.")
    db.add(g12)
    db.commit()
    db.refresh(g12)
    db.add(TariffRate(tariff_id=g12.id, time_start=time(0, 0), time_end=time(5, 59, 59), price_per_kwh=0.75))
    db.add(TariffRate(tariff_id=g12.id, time_start=time(6, 0), time_end=time(12, 59, 59), price_per_kwh=1.35))
    db.add(TariffRate(tariff_id=g12.id, time_start=time(13, 0), time_end=time(15, 59, 59), price_per_kwh=0.75))
    db.add(TariffRate(tariff_id=g12.id, time_start=time(16, 0), time_end=time(21, 59, 59), price_per_kwh=1.35))
    db.add(TariffRate(tariff_id=g12.id, time_start=time(22, 0), time_end=time(23, 59, 59), price_per_kwh=0.75))

    dynamic = Tariff(name="Dynamiczna", type="dynamiczna", description="Symulacja taryfy opartej o ceny giełdowe RDN (zmiany kwadransowe).")
    db.add(dynamic)
    db.commit()
    db.refresh(dynamic)
    
    base_time = datetime(2020, 1, 1, 0, 0)
    
    for i in range(96):
        start_dt = base_time + timedelta(minutes=15 * i)
        end_dt = start_dt + timedelta(minutes=14, seconds=59)
        
        hr = start_dt.hour
        if 0 <= hr < 6:
            price = 0.65
        elif 6 <= hr < 10:
            price = 1.20
        elif 10 <= hr < 15:
            price = 0.40
        elif 15 <= hr < 20:
            price = 2.10
        else:
            price = 1.00
        
        price += (i % 4) * 0.02
        
        db.add(TariffRate(
            tariff_id=dynamic.id, 
            time_start=start_dt.time(), 
            time_end=end_dt.time(), 
            price_per_kwh=round(price, 4)
        ))

    db.commit()
    db.close()
    print("Sukces! Taryfy z rozdzielczością 15-minutową zostały wgrane do bazy.")

if __name__ == "__main__":
    seed_tariffs()
import requests
from datetime import date
from sqlalchemy.orm import Session
from app.models.models import DynamicPrice


def ensure_dynamic_prices(start_date: date, end_date: date, db: Session):
    existing_days = (
        db.query(DynamicPrice.date)
        .filter(DynamicPrice.date >= start_date)
        .filter(DynamicPrice.date <= end_date)
        .distinct()
        .count()
    )

    total_days_needed = (end_date - start_date).days + 1

    if existing_days >= total_days_needed:
        return

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=business_date ge '{start_str}' and business_date le '{end_str}'"

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get("value"):
                new_prices = []
                for item in data["value"]:
                    date_val = item.get("business_date") or item.get("Data")
                    hour_val = item.get("period") or item.get("Godzina")
                    price_val = item.get("rce_pln") or item.get("RCE_PLN")

                    if not date_val or not hour_val or price_val is None:
                        continue

                    item_date = date.fromisoformat(date_val[:10])
                    hour_str = str(hour_val).strip()
                    price_per_kwh = float(price_val) / 1000.0

                    if "-" in hour_str:
                        time_label = hour_str.split("-")[0].strip()

                        exists = (
                            db.query(DynamicPrice)
                            .filter_by(date=item_date, hour=time_label)
                            .first()
                        )
                        if not exists:
                            new_prices.append(
                                DynamicPrice(
                                    date=item_date,
                                    hour=time_label,
                                    price_per_kwh=round(price_per_kwh, 4),
                                )
                            )
                    else:
                        hour_int = int(hour_str)
                        base_hour = hour_int - 1
                        for minute in ["00", "15", "30", "45"]:
                            time_label = f"{base_hour:02d}:{minute}"
                            exists = (
                                db.query(DynamicPrice)
                                .filter_by(date=item_date, hour=time_label)
                                .first()
                            )
                            if not exists:
                                new_prices.append(
                                    DynamicPrice(
                                        date=item_date,
                                        hour=time_label,
                                        price_per_kwh=round(price_per_kwh, 4),
                                    )
                                )

                if new_prices:
                    db.add_all(new_prices)
                    db.commit()
    except requests.exceptions.RequestException:
        pass

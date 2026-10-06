from sqlalchemy.orm import Session

from app.models.Tariff import Tariff
from app.models.TariffRate import TariffRate



class TariffRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self):
        return self.db.query(Tariff).order_by(Tariff.name).all()

    def get_by_id(self, tariff_id: int):
        return self.db.query(Tariff).filter(Tariff.id == tariff_id).first()

    def get_by_name(self, name: str):
        return self.db.query(Tariff).filter(Tariff.name == name).first()

    def get_rates_for_tariff(self, tariff_id: int):
        return self.db.query(TariffRate).filter(TariffRate.tariff_id == tariff_id).all()

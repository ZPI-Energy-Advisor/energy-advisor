from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models.EnergyReading import EnergyReading



class EnergyReadingRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_file(
        self,
        energy_data_file_id: UUID,
        readings: list[tuple[datetime, float, float]],
    ) -> None:
        """Zapisuje odczyty (czas, pobór, oddanie) jednym wsadowym INSERT-em.

        Dodaje do bieżącej transakcji; commit robi zapis pliku na końcu uploadu.
        """
        self.db.query(EnergyReading).filter(
            EnergyReading.energy_data_file_id == energy_data_file_id
        ).delete(synchronize_session=False)
        if not readings:
            return
        self.db.execute(
            insert(EnergyReading),
            [
                {
                    "energy_data_file_id": energy_data_file_id,
                    "measured_at": measured_at,
                    "energy_kwh": Decimal(str(energy_kwh)),
                    "exported_kwh": Decimal(str(exported_kwh)),
                }
                for measured_at, energy_kwh, exported_kwh in readings
            ],
        )

    def list_for_file(self, energy_data_file_id: UUID) -> list[EnergyReading]:
        return (
            self.db.query(EnergyReading)
            .filter(EnergyReading.energy_data_file_id == energy_data_file_id)
            .order_by(EnergyReading.measured_at.asc())
            .all()
        )

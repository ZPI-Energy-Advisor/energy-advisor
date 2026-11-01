from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.EnergyReading import EnergyReading



class EnergyReadingRepository:
    def __init__(self, db: Session):
        self.db = db

    def replace_for_file(
        self,
        energy_data_file_id: UUID,
        readings: list[tuple[datetime, float]],
    ) -> None:
        try:
            self.db.query(EnergyReading).filter(
                EnergyReading.energy_data_file_id == energy_data_file_id
            ).delete(synchronize_session=False)
            self.db.add_all(
                [
                    EnergyReading(
                        energy_data_file_id=energy_data_file_id,
                        measured_at=measured_at,
                        energy_kwh=Decimal(str(energy_kwh)),
                    )
                    for measured_at, energy_kwh in readings
                ]
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def list_for_file(self, energy_data_file_id: UUID) -> list[EnergyReading]:
        return (
            self.db.query(EnergyReading)
            .filter(EnergyReading.energy_data_file_id == energy_data_file_id)
            .order_by(EnergyReading.measured_at.asc())
            .all()
        )

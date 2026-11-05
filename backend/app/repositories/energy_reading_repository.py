from datetime import datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import case, insert, select
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

    def merged_for_files(
        self, file_ids: list[UUID], start: datetime, end: datetime
    ) -> list[tuple[datetime, float, float]]:
        """Odczyty (czas lokalny, pobór, oddanie) z [start, end); przy nakładaniu wygrywa nowszy upload.

        `file_ids` są posortowane od najstarszego do najnowszego uploadu, jak przy scalaniu serii.
        """
        if not file_ids:
            return []
        order = case({file_id: index for index, file_id in enumerate(file_ids)}, value=EnergyReading.energy_data_file_id)
        rows = self.db.execute(
            select(EnergyReading.measured_at, EnergyReading.energy_kwh, EnergyReading.exported_kwh)
            .where(
                EnergyReading.energy_data_file_id.in_(file_ids),
                EnergyReading.measured_at >= start,
                EnergyReading.measured_at < end,
            )
            .order_by(EnergyReading.measured_at, order.desc())
            .distinct(EnergyReading.measured_at)
        ).all()
        return [(measured_at, float(used), float(exported)) for measured_at, used, exported in rows]

    def list_for_file(self, energy_data_file_id: UUID) -> list[EnergyReading]:
        return (
            self.db.query(EnergyReading)
            .filter(EnergyReading.energy_data_file_id == energy_data_file_id)
            .order_by(EnergyReading.measured_at.asc())
            .all()
        )

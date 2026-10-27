from datetime import date
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.EnergyDataFile import EnergyDataFile



class EnergyDataFileRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: UUID, file_name: str) -> EnergyDataFile:
        energy_file = EnergyDataFile(
            user_id=user_id,
            file_name=file_name,
            status=EnergyDataFile.STATUS_PROCESSING,
        )
        self.db.add(energy_file)
        self.db.commit()
        self.db.refresh(energy_file)
        return energy_file

    def save(self, energy_file: EnergyDataFile) -> EnergyDataFile:
        self.db.commit()
        self.db.refresh(energy_file)
        return energy_file

    def rollback(self) -> None:
        self.db.rollback()

    def list_by_user_id(self, user_id: UUID, *, offset: int, limit: int) -> tuple[list[EnergyDataFile], int]:
        query = self.db.query(EnergyDataFile).filter(EnergyDataFile.user_id == user_id)
        total = query.count()
        items = (
            query.order_by(EnergyDataFile.uploaded_at.desc(), EnergyDataFile.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    def get_by_id_for_user(self, file_id: UUID, user_id: UUID) -> EnergyDataFile | None:
        return (
            self.db.query(EnergyDataFile)
            .filter(
                EnergyDataFile.id == file_id,
                EnergyDataFile.user_id == user_id,
            )
            .first()
        )

    def list_completed_by_user_id(self, user_id: UUID) -> list[EnergyDataFile]:
        """Poprawnie zaimportowane pliki użytkownika, od najstarszego uploadu."""
        return (
            self.db.query(EnergyDataFile)
            .filter(
                EnergyDataFile.user_id == user_id,
                EnergyDataFile.status == EnergyDataFile.STATUS_COMPLETED,
            )
            .order_by(EnergyDataFile.uploaded_at.asc(), EnergyDataFile.id.asc())
            .all()
        )

    def get_completed_summary(self, user_id: UUID) -> tuple[int, date | None, date | None]:
        """Liczba poprawnych plików użytkownika oraz najwcześniejsza i najpóźniejsza data ich danych."""
        files_count, data_start, data_end = (
            self.db.query(
                func.count(EnergyDataFile.id),
                func.min(EnergyDataFile.data_start),
                func.max(EnergyDataFile.data_end),
            )
            .filter(
                EnergyDataFile.user_id == user_id,
                EnergyDataFile.status == EnergyDataFile.STATUS_COMPLETED,
            )
            .one()
        )
        return files_count, data_start, data_end

    def delete(self, energy_file: EnergyDataFile) -> None:
        # Symulacje pliku usuwa baza (ON DELETE CASCADE na simulations.energy_data_file_id).
        self.db.delete(energy_file)
        self.db.commit()

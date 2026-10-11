from datetime import date
from uuid import UUID

from fastapi import HTTPException, UploadFile

from app.models.EnergyDataFile import EnergyDataFile
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.simulation_repository import SimulationRepository
from app.services.calculation_service import CalculationService



class UploadService:
    def __init__(
        self,
        calculation_service: CalculationService,
        simulation_repository: SimulationRepository,
        energy_file_repository: EnergyDataFileRepository,
    ):
        self.calculation_service = calculation_service
        self.simulation_repository = simulation_repository
        self.energy_file_repository = energy_file_repository

    def process_upload(self, file: UploadFile, user_id: UUID):

        if not file.filename or not file.filename.endswith(".csv"):
            raise HTTPException(
                status_code=400,
                detail="Wymagany plik .csv"
            )

        energy_file = self.energy_file_repository.create(user_id=user_id, file_name=file.filename[:255])

        try:
            simulation_results = self.calculation_service.calculate_all_tariffs(file.file)
        except HTTPException as exc:
            self._mark_failed(energy_file, str(exc.detail))
            raise
        except Exception:
            self._mark_failed(energy_file, "Nieoczekiwany błąd przetwarzania pliku.")
            raise

        statistics = simulation_results.get("statistics", {})
        energy_file.data_start = self._parse_date(statistics.get("data_start"))
        energy_file.data_end = self._parse_date(statistics.get("data_end"))
        energy_file.records_count = statistics.get("records_count")
        energy_file.status = EnergyDataFile.STATUS_COMPLETED
        self.energy_file_repository.save(energy_file)

        new_simulation = self.simulation_repository.create(
            user_id=user_id,
            energy_data_file_id=energy_file.id,
            results=simulation_results,
        )

        return {
            "status": "success",
            "simulation_id": str(new_simulation.id),
            "file_id": str(energy_file.id),
            "file_name": file.filename,
            "summary": simulation_results,
            "message": "Symulacja zakończona i zapisana na Twoim koncie!",
        }

    def _mark_failed(self, energy_file: EnergyDataFile, message: str):
        energy_file.status = EnergyDataFile.STATUS_FAILED
        energy_file.error_message = message
        self.energy_file_repository.save(energy_file)

    @staticmethod
    def _parse_date(value):
        return date.fromisoformat(value) if value else None

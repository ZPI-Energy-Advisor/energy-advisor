import math
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status

from app.models.EnergyDataFile import EnergyDataFile
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.simulation_repository import SimulationRepository
from app.services.calculation_service import CalculationService, has_usage_series, public_results
from app.schemas.energy_file import EnergyDataFileDataResponse, EnergyDataFileListResponse, EnergyDataFileOut



class EnergyFileService:
    def __init__(self, file_repository: EnergyDataFileRepository, simulation_repository: SimulationRepository):
        self.file_repository = file_repository
        self.simulation_repository = simulation_repository

    def list_files(self, user_id: UUID, page: int, page_size: int) -> EnergyDataFileListResponse:
        items, total = self.file_repository.list_by_user_id(
            user_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return EnergyDataFileListResponse(
            items=[EnergyDataFileOut.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=math.ceil(total / page_size),
        )

    def get_file_data(
        self,
        file_id: UUID,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> EnergyDataFileDataResponse:
        # Cudzy plik zwraca 404 tak samo jak nieistniejący - nie zdradzamy, że istnieje.
        energy_file = self.file_repository.get_by_id_for_user(file_id, user_id)
        if not energy_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono pliku.")

        simulation = self.simulation_repository.get_latest_by_file_id(energy_file.id)
        if energy_file.status != EnergyDataFile.STATUS_COMPLETED or not simulation:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Dane pliku nie są dostępne (status: {energy_file.status}).",
            )

        results = simulation.results
        if date_from is None and date_to is None:
            date_from, date_to = energy_file.data_start, energy_file.data_end
        else:
            # Brakujący koniec zakresu oznacza granicę danych w pliku.
            date_from = date_from or energy_file.data_start
            date_to = date_to or energy_file.data_end
            self._validate_range(energy_file, date_from, date_to)
            if not has_usage_series(results):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ten plik został wgrany przed wprowadzeniem filtrowania po datach. "
                    "Wgraj go ponownie, aby móc wybrać zakres.",
                )
            results = CalculationService.calculate_for_range(results, date_from, date_to)

        return EnergyDataFileDataResponse(
            status="success",
            file=EnergyDataFileOut.model_validate(energy_file),
            simulation_id=str(simulation.id),
            created_at=simulation.created_at,
            date_from=date_from,
            date_to=date_to,
            results=public_results(results),
        )

    @staticmethod
    def _validate_range(energy_file: EnergyDataFile, date_from: date | None, date_to: date | None):
        if date_from is None or date_to is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Plik nie ma określonego zakresu dat.",
            )
        if date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Data początkowa nie może być późniejsza niż data końcowa.",
            )
        if date_from < energy_file.data_start or date_to > energy_file.data_end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Zakres musi mieścić się w okresie dostępnych danych "
                    f"({energy_file.data_start:%d.%m.%Y} – {energy_file.data_end:%d.%m.%Y})."
                ),
            )

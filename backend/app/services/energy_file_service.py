import math
from uuid import UUID

from fastapi import HTTPException, status

from app.models.EnergyDataFile import EnergyDataFile
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.simulation_repository import SimulationRepository
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

    def get_file_data(self, file_id: UUID, user_id: UUID) -> EnergyDataFileDataResponse:
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

        return EnergyDataFileDataResponse(
            status="success",
            file=EnergyDataFileOut.model_validate(energy_file),
            simulation_id=str(simulation.id),
            created_at=simulation.created_at,
            results=simulation.results,
        )

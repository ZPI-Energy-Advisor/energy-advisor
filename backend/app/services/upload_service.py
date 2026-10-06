from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.repositories.simulation_repository import SimulationRepository
from app.repositories.user_repository import UserRepository
from app.services.calculation_service import CalculationService



class UploadService:
    def __init__(self, calculation_service: CalculationService, user_repository: UserRepository, simulation_repository: SimulationRepository):
        self.calculation_service = calculation_service
        self.user_repository = user_repository
        self.simulation_repository = simulation_repository

    def process_upload(self, file: UploadFile, user_email: str):
        if not file.filename or not file.filename.endswith(".csv"):
            raise HTTPException(status_code=400, detail="Wymagany plik .csv")

        user = self.user_repository.get_by_email(user_email)
        if not user:
            raise HTTPException(status_code=404, detail="Nie znaleziono zalogowanego użytkownika.")

        simulation_results = self.calculation_service.calculate_all_tariffs(file.file)
        new_simulation = self.simulation_repository.create(
            user_id=user.id,
            results=simulation_results,
        )

        return {
            "status": "success",
            "simulation_id": str(new_simulation.id),
            "file_name": file.filename,
            "summary": simulation_results,
            "message": "Symulacja zakończona i zapisana na Twoim koncie!",
        }

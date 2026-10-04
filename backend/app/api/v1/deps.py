from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.simulation_repository import SimulationRepository
from app.repositories.tariff_repository import TariffRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.tariff_service import TariffService
from app.services.calculation_service import CalculationService
from app.services.simulation_service import SimulationService
from app.services.upload_service import UploadService
from app.services.user_service import UserService



def get_tariff_repository(db: Session = Depends(get_db)) -> TariffRepository:
    return TariffRepository(db)


def get_tariff_service(repository: TariffRepository = Depends(get_tariff_repository)) -> TariffService:
    return TariffService(repository)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_auth_service(repository: UserRepository = Depends(get_user_repository)) -> AuthService:
    return AuthService(repository)

def get_user_service(repository: UserRepository = Depends(get_user_repository)) -> UserService:
    return UserService(repository)


def get_simulation_repository(db: Session = Depends(get_db)) -> SimulationRepository:
    return SimulationRepository(db)


def get_simulation_service(repository: SimulationRepository = Depends(get_simulation_repository)) -> SimulationService:
    return SimulationService(repository)


def get_calculation_service(db: Session = Depends(get_db)) -> CalculationService:
    return CalculationService(db)


def get_upload_service(
    calculation_service: CalculationService = Depends(get_calculation_service),
    user_repository: UserRepository = Depends(get_user_repository),
    simulation_repository: SimulationRepository = Depends(get_simulation_repository),
) -> UploadService:
    return UploadService(calculation_service=calculation_service, user_repository=user_repository, simulation_repository=simulation_repository)
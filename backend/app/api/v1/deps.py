from uuid import UUID
import jwt
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer


from app.models.User import User
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
from app.config import SECRET_KEY, SIGNATURE_ALGORITHM
from app.models.User import User



def get_tariff_repository(db: Session = Depends(get_db)) -> TariffRepository:
    return TariffRepository(db)


def get_tariff_service(repository: TariffRepository = Depends(get_tariff_repository)) -> TariffService:
    return TariffService(repository)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_auth_service(repository: UserRepository = Depends(get_user_repository)) -> AuthService:
    return AuthService(repository)


def get_user_service(
    repository: UserRepository = Depends(get_user_repository),
    tariff_repository: TariffRepository = Depends(get_tariff_repository),
) -> UserService:
    return UserService(repository, tariff_repository)


def get_simulation_repository(db: Session = Depends(get_db)) -> SimulationRepository:
    return SimulationRepository(db)


def get_simulation_service(repository: SimulationRepository = Depends(get_simulation_repository)) -> SimulationService:
    return SimulationService(repository)


def get_calculation_service(tariff_repository: TariffRepository = Depends(get_tariff_repository)) -> CalculationService:
    return CalculationService(tariff_repository)


def get_upload_service(
    calculation_service: CalculationService = Depends(get_calculation_service),
    user_repository: UserRepository = Depends(get_user_repository),
    simulation_repository: SimulationRepository = Depends(get_simulation_repository),
) -> UploadService:
    return UploadService(calculation_service=calculation_service, user_repository=user_repository, simulation_repository=simulation_repository)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_authenticated_user(token: str = Depends(oauth2_scheme), user_repository: UserRepository = Depends(get_user_repository)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nie udało się zweryfikować danych uwierzytelniających",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[SIGNATURE_ALGORITHM])
        user_id_str = payload.get("sub")

        if user_id_str is None or payload.get("type") != "access":
            raise credentials_exception

        user_id = UUID(user_id_str)

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token wygasł",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.InvalidTokenError, ValueError):
        raise credentials_exception

    user = user_repository.get_by_id(user_id)

    if user is None:
        raise credentials_exception

    return user
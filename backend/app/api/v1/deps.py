import secrets
from typing import Iterator
from uuid import UUID
import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer


from app.models.User import User
from app.database import get_db
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.simulation_repository import SimulationRepository
from app.repositories.tariff_repository import TariffRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.tariff_service import TariffService
from app.services.calculation_service import CalculationService
from app.services.dynamic_price_service import DynamicPriceService
from app.services.energy_file_service import EnergyFileService
from app.services.price_sync_service import PriceSyncService
from app.services.pricing_strategies import build_pricing_strategies
from app.services.simulation_service import SimulationService
from app.services.upload_service import UploadService
from app.services.user_service import UserService
from app.providers.prices.pse_provider import PseRcePriceProvider
from app.core.price_sync_factory import build_http_client, build_price_sync_service
from app.config import PRICE_SYNC_ADMIN_KEY, SECRET_KEY, SIGNATURE_ALGORITHM



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


def get_dynamic_price_repository(db: Session = Depends(get_db)) -> DynamicPriceRepository:
    return DynamicPriceRepository(db)


def get_calculation_service(
    tariff_repository: TariffRepository = Depends(get_tariff_repository),
    dynamic_price_repository: DynamicPriceRepository = Depends(get_dynamic_price_repository),
) -> CalculationService:
    strategies = build_pricing_strategies(tariff_repository, dynamic_price_repository)
    return CalculationService(tariff_repository, pricing_strategies=strategies)


def get_dynamic_price_service(
    repository: DynamicPriceRepository = Depends(get_dynamic_price_repository),
    tariff_repository: TariffRepository = Depends(get_tariff_repository),
) -> DynamicPriceService:
    return DynamicPriceService(repository, source=PseRcePriceProvider.source, tariff_repository=tariff_repository)


def get_price_sync_service(db: Session = Depends(get_db)) -> Iterator[PriceSyncService]:
    http_client = build_http_client()
    try:
        yield build_price_sync_service(db, http_client)
    finally:
        http_client.close()


def get_price_sync_admin_key() -> str | None:
    return PRICE_SYNC_ADMIN_KEY


def require_price_sync_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    admin_key: str | None = Depends(get_price_sync_admin_key),
) -> None:
    if not admin_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ręczna synchronizacja jest wyłączona (brak PRICE_SYNC_ADMIN_KEY).",
        )
    if not x_admin_key or not secrets.compare_digest(x_admin_key, admin_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy klucz administracyjny.",
        )


def get_energy_file_repository(db: Session = Depends(get_db)) -> EnergyDataFileRepository:
    return EnergyDataFileRepository(db)


def get_energy_file_service(
    file_repository: EnergyDataFileRepository = Depends(get_energy_file_repository),
    simulation_repository: SimulationRepository = Depends(get_simulation_repository),
) -> EnergyFileService:
    return EnergyFileService(file_repository, simulation_repository)


def get_upload_service(
    calculation_service: CalculationService = Depends(get_calculation_service),
    simulation_repository: SimulationRepository = Depends(get_simulation_repository),
    energy_file_repository: EnergyDataFileRepository = Depends(get_energy_file_repository),
    user_repository: UserRepository = Depends(get_user_repository),
) -> UploadService:
    return UploadService(
        calculation_service=calculation_service,
        simulation_repository=simulation_repository,
        energy_file_repository=energy_file_repository,
        user_repository=user_repository,
    )


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
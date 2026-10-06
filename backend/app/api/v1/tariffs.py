from fastapi import APIRouter, Depends

from app.api.v1.deps import get_tariff_service, get_user_service
from app.schemas.tariff import TariffListResponse, TariffUpdateRequest
from app.services.tariff_service import TariffService
from app.services.user_service import UserService



router = APIRouter(prefix="/tariffs", tags=["Tariffs"])


@router.get("/", response_model=TariffListResponse)
def get_all_tariffs(service: TariffService = Depends(get_tariff_service)):
    return service.get_all()


@router.patch("/current-tariff")
def update_user_tariff(
    payload: TariffUpdateRequest,
    service: UserService = Depends(get_user_service),
):
    return service.update_current_tariff(payload.email, payload.new_tariff)
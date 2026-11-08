from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import get_authenticated_user, get_tariff_catalog_service
from app.models.User import User
from app.schemas.other import DistributionOperatorEnum
from app.schemas.tariff_catalog import TariffCatalogResponse, TariffOptionsResponse
from app.services.tariff_catalog_service import TariffCatalogService


router = APIRouter(
    prefix="/tariffs",
    tags=["Tariffs"],
)


@router.get("/catalog", response_model=TariffCatalogResponse)
def get_tariff_catalog(
    operator: DistributionOperatorEnum = Query(..., description="Operator systemu dystrybucyjnego"),
    on_date: date | None = Query(default=None, alias="date", description="Dzień (domyślnie dziś, Europe/Warsaw)"),
    user: User = Depends(get_authenticated_user),
    service: TariffCatalogService = Depends(get_tariff_catalog_service),
):
    day = on_date or datetime.now(ZoneInfo("Europe/Warsaw")).date()
    return service.catalog(operator, day)


@router.get("/options", response_model=TariffOptionsResponse)
def get_tariff_options(
    operator: DistributionOperatorEnum = Query(..., description="Operator systemu dystrybucyjnego"),
    user: User = Depends(get_authenticated_user),
    service: TariffCatalogService = Depends(get_tariff_catalog_service),
):
    return service.options(operator)

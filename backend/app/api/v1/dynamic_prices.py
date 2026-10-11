from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.api.v1.deps import (
    get_authenticated_user,
    get_dynamic_price_service,
    get_price_sync_service,
    require_price_sync_admin_key,
)
from app.models.PriceSyncRun import PriceSyncTrigger
from app.schemas.dynamic_price import (
    DynamicPriceDayResponse,
    PriceSyncRequest,
    PriceSyncRunOut,
    PriceSyncStatusResponse,
)
from app.services.dynamic_price_service import DynamicPriceService
from app.services.price_sync_service import PriceSyncService, SyncAlreadyRunningError



router = APIRouter(
    prefix="/dynamic-prices",
    tags=["Dynamic Prices"],
)


@router.post(
    "/sync",
    response_model=PriceSyncRunOut,
    dependencies=[Depends(require_price_sync_admin_key)],
)
def sync_dynamic_prices(
    payload: PriceSyncRequest | None = Body(default=None),
    service: PriceSyncService = Depends(get_price_sync_service),
):
    request = payload or PriceSyncRequest()
    try:
        return service.sync(request.date_from, request.date_to, trigger=PriceSyncTrigger.MANUAL)
    except SyncAlreadyRunningError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get(
    "/sync/status",
    response_model=PriceSyncStatusResponse,
    dependencies=[Depends(get_authenticated_user)],
)
def get_sync_status(service: PriceSyncService = Depends(get_price_sync_service)):
    summary = service.get_status()
    return PriceSyncStatusResponse(
        source=summary.source,
        last_run=summary.last_run,
        last_successful_run=summary.last_successful_run,
    )


@router.get(
    "",
    response_model=DynamicPriceDayResponse,
    dependencies=[Depends(get_authenticated_user)],
)
def get_dynamic_prices(
    business_date: date = Query(..., description="Doba handlowa (Europe/Warsaw), np. 2026-10-10"),
    service: DynamicPriceService = Depends(get_dynamic_price_service),
):
    return service.get_day(business_date)

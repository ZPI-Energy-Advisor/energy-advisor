from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_authenticated_user, get_device_usage_service, get_energy_file_service
from app.models.EnergyDataFile import EnergyDataFile
from app.models.User import User
from app.schemas.energy_file import (
    ALL_DEVICE_FILES_SOURCE_ID,
    ALL_FILES_SOURCE_ID,
    EnergyDataFileDataResponse,
    EnergyDataFileListResponse,
)
from app.schemas.device_usage import DeviceUsageGroupBy, DeviceUsageResolution, DeviceUsageResponse
from app.schemas.schedule import ScheduleResponse
from app.services.device_usage_service import DeviceUsageService
from app.services.dynamic_price_service import DynamicTariffNotFoundError
from app.services.energy_file_service import EnergyFileService



router = APIRouter(
    prefix="/energy-files",
    tags=["Energy Files"],
)


@router.get("", response_model=EnergyDataFileListResponse)
def list_energy_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    return service.list_files(user.id, page, page_size)


DATE_FROM_QUERY = Query(None, alias="from", description="Początek zakresu (RRRR-MM-DD), włącznie.")
DATE_TO_QUERY = Query(None, alias="to", description="Koniec zakresu (RRRR-MM-DD), włącznie.")


# Musi być zarejestrowany przed /{file_id}/data, inaczej "all" trafiłoby do walidacji UUID.
@router.get(f"/{ALL_FILES_SOURCE_ID}/data", response_model=EnergyDataFileDataResponse)
def get_all_files_data(
    date_from: date | None = DATE_FROM_QUERY,
    date_to: date | None = DATE_TO_QUERY,
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    return service.get_all_files_data(user.id, EnergyDataFile.SOURCE_METER, date_from, date_to)


@router.get(f"/{ALL_DEVICE_FILES_SOURCE_ID}/data", response_model=EnergyDataFileDataResponse)
def get_all_device_files_data(
    date_from: date | None = DATE_FROM_QUERY,
    date_to: date | None = DATE_TO_QUERY,
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    return service.get_all_files_data(user.id, EnergyDataFile.SOURCE_DEVICES, date_from, date_to)


@router.get("/{file_id}/data", response_model=EnergyDataFileDataResponse)
def get_energy_file_data(
    file_id: UUID,
    date_from: date | None = DATE_FROM_QUERY,
    date_to: date | None = DATE_TO_QUERY,
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    return service.get_file_data(file_id, user.id, date_from, date_to)


@router.get("/{source_id}/devices/usage", response_model=DeviceUsageResponse)
def get_device_usage(
    source_id: str,
    group_by: DeviceUsageGroupBy = Query(DeviceUsageGroupBy.CATEGORY, description="Podział: kategoria, typ albo urządzenie."),
    resolution: DeviceUsageResolution = Query(DeviceUsageResolution.HOUR, description="Długość okresu na osi czasu."),
    date_from: date | None = DATE_FROM_QUERY,
    date_to: date | None = DATE_TO_QUERY,
    tariff: str | None = Query(None, description="Taryfa kosztów; domyślnie taryfa z profilu, a bez niej G11."),
    category: str | None = Query(None, description="Tylko urządzenia z tej kategorii, np. AGD."),
    device_type: str | None = Query(None, alias="type", description="Tylko urządzenia tego typu, np. ev_charger."),
    flexible: bool = Query(False, description="Tylko urządzenia, które można przenieść na inne godziny."),
    meter: str | None = Query(
        None, description="Plik z licznika albo „all”: dodaje grupę „Reszta domu” = licznik − urządzenia."
    ),
    user: User = Depends(get_authenticated_user),
    service: DeviceUsageService = Depends(get_device_usage_service),
):
    """Zużycie i koszt urządzeń pliku albo „Wszystkich plików urządzeń” (source_id = all-devices)."""
    return service.get_usage(
        source_id,
        user.id,
        group_by=group_by,
        resolution=resolution,
        date_from=date_from,
        date_to=date_to,
        tariff=tariff,
        category=category,
        device_type=device_type,
        flexible_only=flexible,
        meter=meter,
    )


@router.get("/{file_id}/schedule", response_model=ScheduleResponse)
def get_energy_file_schedule(
    file_id: UUID,
    date_from: date | None = DATE_FROM_QUERY,
    date_to: date | None = DATE_TO_QUERY,
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    try:
        return service.get_file_schedule(file_id, user.id, date_from, date_to)
    except DynamicTariffNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_energy_file(
    file_id: UUID,
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    service.delete_file(file_id, user)

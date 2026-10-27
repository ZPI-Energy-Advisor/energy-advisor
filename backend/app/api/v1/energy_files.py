from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import get_authenticated_user, get_energy_file_service
from app.models.EnergyDataFile import EnergyDataFile
from app.models.User import User
from app.schemas.energy_file import (
    ALL_DEVICE_FILES_SOURCE_ID,
    ALL_FILES_SOURCE_ID,
    EnergyDataFileDataResponse,
    EnergyDataFileListResponse,
)
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


# Źródła zbiorcze muszą być zarejestrowane przed /{file_id}/data, inaczej "all" trafiłoby do walidacji UUID.
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


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_energy_file(
    file_id: UUID,
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    service.delete_file(file_id, user.id)

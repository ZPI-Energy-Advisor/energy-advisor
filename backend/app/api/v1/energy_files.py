from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import get_authenticated_user, get_energy_file_service
from app.models.User import User
from app.schemas.energy_file import EnergyDataFileDataResponse, EnergyDataFileListResponse
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


@router.get("/{file_id}/data", response_model=EnergyDataFileDataResponse)
def get_energy_file_data(
    file_id: UUID,
    date_from: date | None = Query(None, alias="from", description="Początek zakresu (RRRR-MM-DD), włącznie."),
    date_to: date | None = Query(None, alias="to", description="Koniec zakresu (RRRR-MM-DD), włącznie."),
    user: User = Depends(get_authenticated_user),
    service: EnergyFileService = Depends(get_energy_file_service),
):
    return service.get_file_data(file_id, user.id, date_from, date_to)

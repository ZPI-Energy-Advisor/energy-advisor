from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from app.api.v1.deps import (
    get_authenticated_user,
    get_new_calculations_service,
    get_upload_service,
)
from app.models.User import User
from app.schemas.calculation import CalculationDetails
from app.schemas.simulation import UploadSimulationResponse
from app.services.new_calculations_service import CalculationsService
from app.services.upload_service import UploadService
from app.services.weather_sync import sync_history_after_upload



router = APIRouter(
    prefix="/upload",
    tags=["Upload & Simulation"]
)


@router.post("", response_model=UploadSimulationResponse)
def upload_energy_data(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_authenticated_user),
    service: UploadService = Depends(get_upload_service),
):
    result = service.process_upload(file=file, user=user)
    background_tasks.add_task(sync_history_after_upload, user.id)
    return result


@router.get("/calculation-details/{file_id}", response_model=CalculationDetails)
def get_calculation_details(
    file_id: UUID,
    user: User = Depends(get_authenticated_user),
    service: CalculationsService = Depends(get_new_calculations_service),
):
    return service.perform_tariff_calculations(user_id=user.id, file_id=file_id)

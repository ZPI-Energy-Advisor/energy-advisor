from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.models import User
from app.api.v1.deps import get_authenticated_user, get_upload_service
from app.schemas.simulation import UploadSimulationResponse
from app.services.upload_service import UploadService



router = APIRouter(
    prefix="/upload", 
    tags=["Upload & Simulation"]
)


@router.post("", response_model=UploadSimulationResponse)
def upload_energy_data(
    file: UploadFile = File(...),
    user: User = Depends(get_authenticated_user),
    service: UploadService = Depends(get_upload_service),
):
    return service.process_upload(file=file, user_id=user.id)
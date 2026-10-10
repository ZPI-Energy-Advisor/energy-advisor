from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_authenticated_user, get_simulation_service
from app.models.User import User
from app.services.simulation_service import SimulationService
from app.schemas.simulation import SimulationResultResponse


router = APIRouter(
    prefix="/results",
    tags=["Results"],
    dependencies=[Depends(get_authenticated_user)],
)


@router.get("", response_model=SimulationResultResponse)
def get_latest_user_simulation(
    user: User = Depends(get_authenticated_user),
    service: SimulationService = Depends(get_simulation_service),
):
    return service.get_latest_by_user_id(user.id)


@router.get("/{simulation_id}", response_model=SimulationResultResponse)
def get_simulation_results(
    simulation_id: UUID,
    user: User = Depends(get_authenticated_user),
    service: SimulationService = Depends(get_simulation_service),
):
    return service.get_simulation_results(simulation_id, user.id)

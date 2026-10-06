from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_simulation_service
from app.services.simulation_service import SimulationService
from app.schemas.simulation import SimulationResultResponse



router = APIRouter(prefix="/results", tags=["Results"])


@router.get("/user/{user_id}", response_model=SimulationResultResponse)
def get_latest_user_simulation(
    user_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    return service.get_latest_by_user_id(user_id)


@router.get("/{simulation_id}", response_model=SimulationResultResponse)
def get_simulation_results(
    simulation_id: str,
    service: SimulationService = Depends(get_simulation_service),
):
    return service.get_simulation_results(simulation_id)

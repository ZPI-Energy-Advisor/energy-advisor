from fastapi import APIRouter, Depends

from app.api.v1.deps import get_authenticated_user, get_planning_service
from app.models.User import User
from app.schemas.planning import PlanningPreferences, PlanningPreferencesOut
from app.services.planning_service import PlanningService


# Plan na jutro dla każdego zalogowanego: urządzenia z jego plików, bez huba Smart Home.
router = APIRouter(
    prefix="/planning",
    tags=["Planning"],
)


@router.get("/preferences", response_model=PlanningPreferencesOut)
def get_planning_preferences(
    user: User = Depends(get_authenticated_user),
    service: PlanningService = Depends(get_planning_service),
):
    """Ustawienia planu na jutro: urządzenia shiftable i interruptible z domyślnymi przedziałami."""
    return service.get(user)


@router.put("/preferences", response_model=PlanningPreferencesOut)
def save_planning_preferences(
    preferences: PlanningPreferences,
    user: User = Depends(get_authenticated_user),
    service: PlanningService = Depends(get_planning_service),
):
    """Zapis ustawień (nadpisuje poprzednie). Błędy wymagań są przy polach urządzeń."""
    return service.save(user, preferences)

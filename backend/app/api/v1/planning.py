from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import get_authenticated_user, get_plan_service, get_planning_service
from app.models.User import User
from app.schemas.day_plan import DayPlanOut, DayPlanRequest
from app.schemas.planning import PlanningPreferences, PlanningPreferencesOut
from app.services.plan_service import PlanService
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
    """Ustawienia planu na jutro: urządzenia z programami, auto, pompa ciepła i bojler z domyślnymi ustawieniami."""
    return service.get(user)


@router.put("/preferences", response_model=PlanningPreferencesOut)
def save_planning_preferences(
    preferences: PlanningPreferences,
    user: User = Depends(get_authenticated_user),
    service: PlanningService = Depends(get_planning_service),
):
    """Zapis ustawień (nadpisuje poprzednie). Błędy wymagań są przy polach urządzeń."""
    return service.save(user, preferences)


@router.post("/plans", response_model=DayPlanOut, status_code=status.HTTP_201_CREATED)
def create_day_plan(
    request: DayPlanRequest,
    user: User = Depends(get_authenticated_user),
    service: PlanService = Depends(get_plan_service),
):
    """Plan pracy urządzeń na jutro (albo na `plan_date`) z zapisanych ustawień, jako szkic.

    Bez cen dynamicznych na ten dzień: 409 z `detail.code = "no_prices"`, komunikatem o publikacji
    i ostatnim dniem z cenami (`latest_price_date`) do planu demo.
    """
    return service.create(user, request.plan_date)


@router.get("/plans/current", response_model=DayPlanOut | None)
def get_current_day_plan(
    user: User = Depends(get_authenticated_user),
    service: PlanService = Depends(get_plan_service),
):
    """Ostatnio ułożony plan użytkownika albo null."""
    return service.current(user)


@router.post("/plans/{plan_id}/approve", response_model=DayPlanOut)
def approve_day_plan(
    plan_id: UUID,
    user: User = Depends(get_authenticated_user),
    service: PlanService = Depends(get_plan_service),
):
    """Zatwierdza plan (status `approved`); ponowne ułożenie wraca do szkicu."""
    return service.approve(user, plan_id)

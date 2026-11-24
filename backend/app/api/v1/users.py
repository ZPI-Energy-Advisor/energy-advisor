from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from app.api.v1.deps import get_authenticated_user, get_home_service, get_user_service
from app.config import RATE_LIMIT_ADDRESS_LOOKUP
from app.core.rate_limit import limiter
from app.models.User import User
from app.schemas.user import CurrentUserResponse, DeleteAccountRequest
from app.schemas.user_profile import UserProfile
from app.services.home_location import AddressLookup, lookup_address
from app.services.home_service import HomeService
from app.services.user_service import UserService
from app.services.weather_sync import sync_after_profile_change



router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user(
    user: User = Depends(get_authenticated_user),
    service: UserService = Depends(get_user_service),
    home_service: HomeService = Depends(get_home_service),
):
    current = service.get_current_user(user)
    current.home_owner = home_service.is_owner(user)
    return current


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_current_user(
    request: DeleteAccountRequest,
    user: User = Depends(get_authenticated_user),
    service: UserService = Depends(get_user_service),
    home_service: HomeService = Depends(get_home_service),
):
    """Usuwa konto ze wszystkimi danymi (prawo do usunięcia). Potwierdzenie: e-mail konta w `confirm_email`.

    Właściciel podłączonego domu Smart Home najpierw go odłącza (hub zatrzymuje urządzenia); gdy hub nie
    odpowiada, konto zostaje (503), żeby w hubie nie zostały urządzenia usuniętego konta.
    """
    service.check_deletion_confirmed(user, request.confirm_email)
    home_service.release_before_account_deletion(user)
    service.delete_account(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/profile", response_model=UserProfile)
def get_user_profile(
    user: User = Depends(get_authenticated_user),
    service: UserService = Depends(get_user_service),
):
    return service.get_profile(user)


@router.get("/me/profile/address-lookup", response_model=AddressLookup)
@limiter.limit(RATE_LIMIT_ADDRESS_LOOKUP)
def look_up_address(
    request: Request,
    town: str | None = Query(default=None, max_length=100),
    postal_code: str | None = Query(default=None, pattern=r"^\d{2}-\d{3}$"),
    user: User = Depends(get_authenticated_user),
):
    """Sprawdza miejscowość i kod pocztowy bez zapisu profilu; z jednego pola podpowiada drugie."""
    town = (town or "").strip() or None
    if not town and not postal_code:
        raise HTTPException(status_code=422, detail="Podaj miejscowość albo kod pocztowy.")
    return lookup_address(town, postal_code)


@router.put("/me/profile", response_model=UserProfile)
def save_user_profile(
    profile_data: UserProfile,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_authenticated_user),
    service: UserService = Depends(get_user_service),
):
    saved = service.save_profile(user, profile_data)
    background_tasks.add_task(sync_after_profile_change, user.id)
    return saved

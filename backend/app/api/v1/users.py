from fastapi import APIRouter, Depends, Response, status

from app.api.v1.deps import get_authenticated_user, get_home_service, get_user_service
from app.models.User import User
from app.schemas.user import CurrentUserResponse, DeleteAccountRequest
from app.schemas.user_profile import UserProfile
from app.services.home_service import HomeService
from app.services.user_service import UserService



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


@router.put("/me/profile", response_model=UserProfile)
def save_user_profile(
    profile_data: UserProfile,
    user: User = Depends(get_authenticated_user),
    service: UserService = Depends(get_user_service),
):
    return service.save_profile(user, profile_data)

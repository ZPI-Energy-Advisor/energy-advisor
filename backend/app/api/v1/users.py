from fastapi import APIRouter, Depends

from app.api.v1.deps import get_authenticated_user, get_user_service
from app.models.User import User
from app.schemas.user import CurrentUserResponse
from app.schemas.user_profile import UserProfile
from app.services.user_service import UserService



router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user(
    user: User = Depends(get_authenticated_user),
    service: UserService = Depends(get_user_service),
):
    return service.get_current_user(user)


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

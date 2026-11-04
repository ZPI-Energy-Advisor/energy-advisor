from fastapi import HTTPException

from app.models.Tariff import Tariff
from app.models.User import User
from app.repositories.tariff_repository import TariffRepository
from app.repositories.user_repository import UserRepository
from app.schemas.other import TariffTypeEnum
from app.schemas.user import CurrentUserResponse, ProfileTariffSummary
from app.schemas.user_profile import UserProfile
from app.services.tariff_service import tariff_out


class UserService:
    def __init__(self, repository: UserRepository, tariff_repository: TariffRepository):
        self.repository = repository
        self.tariff_repository = tariff_repository

    def get_current_user(self, user: User) -> CurrentUserResponse:
        profile = self.repository.get_profile(user.id)
        tariff_type = profile.consumption_and_tariff.get("tariff_type") if profile else None
        tariff = self._find_tariff(tariff_type) if tariff_type else None

        return CurrentUserResponse(
            email=user.email,
            provider=user.provider,
            current_tariff=tariff_out(tariff) if tariff else None,
            profile=ProfileTariffSummary(exists=profile is not None, tariff_type=tariff_type),
        )

    def _find_tariff(self, tariff_type: str) -> Tariff | None:
        # Taryfa dynamiczna ma w tabeli tariffs inną nazwę niż wartość w profilu.
        if tariff_type == TariffTypeEnum.DYNAMIC.value:
            return self.tariff_repository.get_first_by_type(Tariff.TYPE_DYNAMIC)
        return self.tariff_repository.get_by_code(tariff_type)

    def get_profile(self, user: User) -> UserProfile:
        profile = self.repository.get_profile(user.id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profil użytkownika nie został znaleziony.")
        try:
            return UserProfile.model_validate(profile)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail="Profil użytkownika wymaga ponownego uzupełnienia.",
            ) from exc

    def save_profile(self, user: User, profile_data: UserProfile) -> UserProfile:
        if self.repository.get_profile(user.id):
            profile = self.repository.update_profile(user.id, profile_data)
        else:
            profile = self.repository.create_profile(user.id, profile_data)
        return UserProfile.model_validate(profile)

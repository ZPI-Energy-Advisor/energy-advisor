from fastapi import HTTPException

from app.models.Tariff import Tariff
from app.models.User import User
from app.repositories.tariff_definition_repository import TariffDefinitionRepository
from app.repositories.tariff_repository import TariffRepository
from app.repositories.user_repository import UserRepository
from app.schemas.other import TariffTypeEnum
from app.schemas.user import CurrentUserResponse, ProfileTariffSummary
from app.schemas.user_profile import UserProfile
from app.services.tariff_service import tariff_out


class UserService:
    def __init__(
        self,
        repository: UserRepository,
        tariff_repository: TariffRepository,
        definition_repository: TariffDefinitionRepository | None = None,
    ):
        self.repository = repository
        self.tariff_repository = tariff_repository
        self.definition_repository = definition_repository

    def get_current_user(self, user: User) -> CurrentUserResponse:
        profile = self.repository.get_profile(user.id)
        tariff_type = self._tariff_type(profile)
        tariff = self._find_tariff(tariff_type) if tariff_type else None

        return CurrentUserResponse(
            email=user.email,
            provider=user.provider,
            current_tariff=tariff_out(tariff) if tariff else None,
            profile=ProfileTariffSummary(
                exists=profile is not None,
                needs_update=profile is not None and self._validated(profile) is None,
                tariff_type=tariff_type,
            ),
        )

    def profile_tariff(self, user_id) -> tuple[str | None, Tariff | None]:
        """Taryfa z profilu: wartość z profilu (np. "G13") i odpowiadająca jej taryfa z cennikiem albo None."""
        tariff_type = self._tariff_type(self.repository.get_profile(user_id))
        return tariff_type, self._find_tariff(tariff_type) if tariff_type else None

    @staticmethod
    def _tariff_type(profile) -> str | None:
        # Stary cennik (Dashboard) zna taryfę dynamiczną jako osobną taryfę.
        if not profile:
            return None
        if profile.consumption_and_tariff.get("dynamic_price"):
            return TariffTypeEnum.DYNAMIC.value
        return profile.consumption_and_tariff.get("tariff_type")

    def _find_tariff(self, tariff_type: str) -> Tariff | None:
        # Taryfa dynamiczna ma w tabeli tariffs inną nazwę niż wartość w profilu.
        if tariff_type == TariffTypeEnum.DYNAMIC.value:
            return self.tariff_repository.get_first_by_type(Tariff.TYPE_DYNAMIC)
        return self.tariff_repository.get_by_code(tariff_type)

    def get_profile(self, user: User) -> UserProfile:
        profile = self.repository.get_profile(user.id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profil użytkownika nie został znaleziony.")
        validated = self._validated(profile)
        if validated is None:
            raise HTTPException(status_code=409, detail="Profil użytkownika wymaga ponownego uzupełnienia.")
        return validated

    @staticmethod
    def _validated(profile) -> UserProfile | None:
        """Profil w aktualnym formacie albo None, gdy zapisano go przed zmianą schematu."""
        try:
            return UserProfile.model_validate(profile)
        except ValueError:
            return None

    def _validate_against_rates(self, profile_data: UserProfile) -> None:
        """Odrzuca taryfę i okres rozliczeniowy, których operator nie ma w cenniku (gdy ma w bazie jakiekolwiek stawki)."""
        if self.definition_repository is None:
            return
        operator = profile_data.base_info.distribution_operator
        definitions = self.definition_repository.list_for_operator(operator=operator)
        if not definitions:
            return

        tariffs = sorted(
            {definition.tariff_code.value for definition in definitions if definition.tariff_code != TariffTypeEnum.DYNAMIC}
        )
        tariff_type = profile_data.consumption_and_tariff.tariff_type.value
        if profile_data.consumption_and_tariff.dynamic_price:
            groups = sorted(
                {d.distribution_group.value for d in definitions if d.tariff_code == TariffTypeEnum.DYNAMIC}
            )
            if tariff_type not in groups:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Oferty z ceną dynamiczną u operatora {operator.value} nie liczymy z grupą {tariff_type}. "
                        f"Dostępne grupy: {', '.join(groups) or 'brak'}."
                    ),
                )
        if tariff_type not in tariffs:
            raise HTTPException(
                status_code=422,
                detail=f"Operator {operator.value} nie ma w cenniku taryfy {tariff_type}. Dostępne taryfy: {', '.join(tariffs)}.",
            )

        cycles = sorted(
            {
                fee.billing_cycle_months
                for definition in definitions
                if definition.tariff_code != TariffTypeEnum.DYNAMIC
                for fee in definition.subscription_fees
            }
        )
        billing_cycle = profile_data.base_info.billing_cycle.value
        if cycles and billing_cycle not in cycles:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Operator {operator.value} nie ma w cenniku okresu rozliczeniowego {billing_cycle} mies. "
                    f"Dostępne okresy (w miesiącach): {', '.join(str(cycle) for cycle in cycles)}."
                ),
            )

    def save_profile(self, user: User, profile_data: UserProfile) -> UserProfile:
        self._validate_against_rates(profile_data)
        if self.repository.get_profile(user.id):
            profile = self.repository.update_profile(user.id, profile_data)
        else:
            profile = self.repository.create_profile(user.id, profile_data)
        return UserProfile.model_validate(profile)

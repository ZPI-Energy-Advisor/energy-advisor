from datetime import date

from fastapi import HTTPException
from pydantic import ValidationError

from app.models.User import User
from app.repositories.tariff_definition_repository import TariffDefinitionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.other import TariffTypeEnum
from app.schemas.tariff import TariffOut
from app.schemas.user import CurrentUserResponse, ProfileTariffSummary
from app.schemas.user_profile import UserProfile
from app.services.home_location import AddressError, resolve_location, stored_location
from app.services.tariff_costs import PricingProfile, TariffOption


DELETE_CONFIRMATION_MESSAGE = "Wpisz adres e-mail swojego konta, żeby potwierdzić usunięcie."


def _field_error(field: tuple[str, ...], message: str) -> HTTPException:
    """Błąd 422 w formacie walidacji FastAPI (lista z położeniem pola), żeby formularz pokazał go przy polu."""
    return HTTPException(status_code=422, detail=[{"loc": ["body", *field], "msg": message, "type": "value_error"}])


class UserService:
    def __init__(
        self,
        repository: UserRepository,
        definition_repository: TariffDefinitionRepository | None = None,
        geocoder=None,
    ):
        self.repository = repository
        self.definition_repository = definition_repository
        self.geocoder = geocoder

    @staticmethod
    def check_deletion_confirmed(user: User, confirm_email: str) -> None:
        """Usunięcie konta wymaga wpisania jego e-maila (wielkość liter i spacje na brzegach bez znaczenia)."""
        if confirm_email.strip().lower() != user.email.strip().lower():
            raise _field_error(("confirm_email",), DELETE_CONFIRMATION_MESSAGE)

    def delete_account(self, user: User) -> None:
        self.repository.delete(user.id)

    def get_current_user(self, user: User, today: date | None = None) -> CurrentUserResponse:
        profile = self.repository.get_profile(user.id)
        pricing = PricingProfile.from_saved(profile)

        return CurrentUserResponse(
            email=user.email,
            provider=user.provider,
            current_tariff=self.current_tariff(pricing, today or date.today()) if pricing.from_profile else None,
            profile=ProfileTariffSummary(
                exists=profile is not None,
                needs_update=profile is not None and self._validated(profile) is None,
                tariff_type=self._tariff_type(profile),
            ),
        )

    def current_tariff(self, pricing: PricingProfile, today: date) -> TariffOut | None:
        """Definicja taryfy z profilu w nowym cenniku: operator, kod (albo oferta dynamiczna z grupą) i data."""
        if self.definition_repository is None:
            return None
        definitions = [
            definition
            for definition in self.definition_repository.list_for_operator(operator=pricing.operator)
            if definition.tariff_code == pricing.code and definition.distribution_group == pricing.tariff_type
        ]
        if not definitions:
            return None
        valid_today = [definition for definition in definitions if definition.valid_from <= today <= definition.valid_to]
        definition = valid_today[0] if valid_today else max(definitions, key=lambda item: item.valid_to)
        option = TariffOption(pricing.code, pricing.tariff_type, (definition,))
        return TariffOut(
            code=option.key,
            label=option.label,
            name=definition.name,
            operator=pricing.operator.value,
            tariff_code=pricing.code.value,
            distribution_group=pricing.tariff_type.value,
            dynamic=option.dynamic,
            valid_from=definition.valid_from,
            valid_to=definition.valid_to,
        )

    @staticmethod
    def _tariff_type(profile) -> str | None:
        if not profile:
            return None
        return profile.consumption_and_tariff.get("tariff_type")

    def get_profile(self, user: User) -> UserProfile:
        profile = self.repository.get_profile(user.id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profil użytkownika nie został znaleziony.")
        try:
            data = UserProfile.model_validate(profile)
        except ValidationError as error:
            # Profil zapisany w starszym formacie: oddajemy zapisane dane i pola do uzupełnienia, żeby formularz je oznaczył.
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Profil użytkownika wymaga ponownego uzupełnienia.",
                    "profile": {
                        "base_info": profile.base_info,
                        "consumption_and_tariff": profile.consumption_and_tariff,
                        "pv_config": profile.pv_config,
                    },
                    "fields": sorted({".".join(str(part) for part in item["loc"][:2]) for item in error.errors()}),
                },
            ) from error
        stored = data.base_info.location
        if stored is None or stored.approximate:
            location = resolve_location(data.base_info, stored, self.geocoder, strict=False)
            if location != stored:
                self.repository.update_location(user.id, location.model_dump(mode="json"))
                data.base_info.location = location
        return data

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
                raise _field_error(
                    ("consumption_and_tariff", "dynamic_price"),
                    f"Oferty z ceną dynamiczną u operatora {operator.value} nie liczymy z grupą {tariff_type}. "
                    f"Dostępne grupy: {', '.join(groups) or 'brak'}.",
                )
        if tariff_type not in tariffs:
            raise _field_error(
                ("consumption_and_tariff", "tariff_type"),
                f"Operator {operator.value} nie ma w cenniku taryfy {tariff_type}. Dostępne taryfy: {', '.join(tariffs)}.",
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
            raise _field_error(
                ("base_info", "billing_cycle"),
                f"Operator {operator.value} nie ma w cenniku okresu rozliczeniowego {billing_cycle} mies. "
                f"Dostępne okresy (w miesiącach): {', '.join(str(cycle) for cycle in cycles)}.",
            )

    def save_profile(self, user: User, profile_data: UserProfile) -> UserProfile:
        self._validate_against_rates(profile_data)
        existing = self.repository.get_profile(user.id)
        previous = stored_location(existing.base_info) if existing else None
        try:
            location = resolve_location(profile_data.base_info, previous, self.geocoder)
        except AddressError as error:
            raise HTTPException(
                status_code=422,
                detail=[
                    {"loc": ["body", "base_info", field], "msg": message, "type": "value_error"}
                    for field, message in error.errors.items()
                ],
            ) from error
        profile_data = profile_data.model_copy(
            update={"base_info": profile_data.base_info.model_copy(update={"location": location})}
        )
        if existing:
            profile = self.repository.update_profile(user.id, profile_data)
        else:
            profile = self.repository.create_profile(user.id, profile_data)
        return UserProfile.model_validate(profile)

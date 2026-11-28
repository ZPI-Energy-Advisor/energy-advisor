from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tariff import TariffOut



class ProfileTariffSummary(BaseModel):
    exists: bool
    # Profil zapisany w starszym formacie, który trzeba ponownie zapisać na stronie profilu.
    needs_update: bool = False
    # Taryfa zapisana w profilu (TariffTypeEnum), także gdy operator nie ma jej stawek w cenniku.
    tariff_type: str | None = None
    # Profil ma fotowoltaikę (rozliczenie inne niż „bez PV”); menu pokazuje wtedy ekran Fotowoltaika.
    has_pv: bool = False


class PrivacyPolicyStatus(BaseModel):
    current_version: str
    # Ostatnia wersja zaakceptowana przez użytkownika; None, gdy konto powstało przed ZP-129.
    accepted_version: str | None = None
    accepted_at: datetime | None = None
    # Frontend blokuje aplikację, dopóki użytkownik nie zaakceptuje aktualnej wersji.
    needs_acceptance: bool


class PrivacyConsentRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32)


class DeleteAccountRequest(BaseModel):
    # Potwierdzenie: e-mail konta wpisany przez użytkownika.
    confirm_email: str


class CurrentUserResponse(BaseModel):
    email: str
    provider: str | None = None
    # Definicja z tariff_definitions dla operatora, taryfy i dzisiejszej daty; None bez profilu lub bez stawek.
    current_tariff: TariffOut | None = None
    profile: ProfileTariffSummary
    home_owner: bool = False
    privacy_policy: PrivacyPolicyStatus

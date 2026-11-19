from pydantic import BaseModel

from app.schemas.tariff import TariffOut



class ProfileTariffSummary(BaseModel):
    exists: bool
    # Profil zapisany w starszym formacie, który trzeba ponownie zapisać na stronie profilu.
    needs_update: bool = False
    # Taryfa zapisana w profilu (TariffTypeEnum), także gdy operator nie ma jej stawek w cenniku.
    tariff_type: str | None = None


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

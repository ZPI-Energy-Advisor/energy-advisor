from pydantic import BaseModel

from app.schemas.tariff import TariffOut



class ProfileTariffSummary(BaseModel):
    exists: bool
    # Taryfa zapisana w profilu (TariffTypeEnum), także gdy nie ma jej w tabeli tariffs.
    tariff_type: str | None = None


class CurrentUserResponse(BaseModel):
    email: str
    provider: str | None = None
    # Taryfa z tabeli tariffs odpowiadająca taryfie z profilu; None bez profilu lub bez odpowiednika.
    current_tariff: TariffOut | None = None
    profile: ProfileTariffSummary

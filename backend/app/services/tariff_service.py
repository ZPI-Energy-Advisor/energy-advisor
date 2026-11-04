from app.models.Tariff import Tariff
from app.repositories.tariff_repository import TariffRepository
from app.schemas.other import TariffTypeEnum
from app.schemas.tariff import TariffListResponse, TariffOut


_PROFILE_TARIFF_TYPES = {tariff_type.value.lower(): tariff_type for tariff_type in TariffTypeEnum}


def to_profile_tariff_type(tariff: Tariff) -> TariffTypeEnum | None:
    if tariff.type == Tariff.TYPE_DYNAMIC:
        return TariffTypeEnum.DYNAMIC
    return _PROFILE_TARIFF_TYPES.get(tariff.name.lower())


def tariff_out(tariff: Tariff) -> TariffOut:
    out = TariffOut.model_validate(tariff)
    return out.model_copy(update={"profile_tariff_type": to_profile_tariff_type(tariff)})


class TariffService:
    def __init__(self, repository: TariffRepository):
        self.repository = repository

    def get_all(self) -> TariffListResponse:
        tariffs = self.repository.get_all()
        return TariffListResponse(
            status="success",
            tariffs=[tariff_out(tariff) for tariff in tariffs],
        )

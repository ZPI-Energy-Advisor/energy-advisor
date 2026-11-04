from app.models.Tariff import Tariff
from app.schemas.other import TariffTypeEnum
from app.schemas.tariff import TariffOut


_PROFILE_TARIFF_TYPES = {tariff_type.value.lower(): tariff_type for tariff_type in TariffTypeEnum}


def to_profile_tariff_type(tariff: Tariff) -> TariffTypeEnum | None:
    if tariff.type == Tariff.TYPE_DYNAMIC:
        return TariffTypeEnum.DYNAMIC
    return _PROFILE_TARIFF_TYPES.get(tariff.name.lower())


def tariff_out(tariff: Tariff) -> TariffOut:
    out = TariffOut.model_validate(tariff)
    return out.model_copy(update={"profile_tariff_type": to_profile_tariff_type(tariff)})

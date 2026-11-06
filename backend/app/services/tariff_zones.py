from datetime import datetime

from app.schemas.other import TariffTypeEnum


# Strefa 0 jest najdroższa i odpowiada zone_index 1 w stawkach taryfy, strefa 1 - zone_index 2 itd.
# Godziny są przybliżeniem wspólnym dla wszystkich operatorów, bez sezonów i świąt; docelowe
# godziny per operator i sezon wprowadza ZP-87. Godziny liczone są w czasie lokalnym, tak jak
# znaczniki odczytów.
ZONE_COUNTS = {
    TariffTypeEnum.G11: 1,
    TariffTypeEnum.G12: 2,
    TariffTypeEnum.G12W: 2,
    TariffTypeEnum.G13: 3,
    TariffTypeEnum.G13S: 3,
    TariffTypeEnum.G14D: 4,
    TariffTypeEnum.DYNAMIC: 1,
}
SATURDAY = 5


def zone_count(tariff_type: TariffTypeEnum) -> int:
    if tariff_type not in ZONE_COUNTS:
        raise ValueError(f"Brak mapowania stref dla taryfy {tariff_type.value}.")
    return ZONE_COUNTS[tariff_type]


def zone_for(timestamp: datetime, tariff_type: TariffTypeEnum) -> int:
    """Indeks strefy (0 = najdroższa), do której należy kwadrans zaczynający się o `timestamp`."""
    if zone_count(tariff_type) == 1:
        return 0

    minutes = timestamp.hour * 60 + timestamp.minute
    if tariff_type == TariffTypeEnum.G12W and timestamp.weekday() >= SATURDAY:
        return 1
    if tariff_type in (TariffTypeEnum.G12, TariffTypeEnum.G12W):
        return 0 if 6 * 60 <= minutes < 13 * 60 or 15 * 60 <= minutes < 22 * 60 else 1
    if tariff_type in (TariffTypeEnum.G13, TariffTypeEnum.G13S):
        if 7 * 60 <= minutes < 13 * 60 or 16 * 60 <= minutes < 21 * 60:
            return 0
        if 13 * 60 <= minutes < 16 * 60 or 21 * 60 <= minutes < 22 * 60:
            return 1
        return 2
    # G14d
    if 7 * 60 <= minutes < 13 * 60:
        return 0
    if 13 * 60 <= minutes < 16 * 60:
        return 1
    if 16 * 60 <= minutes < 22 * 60:
        return 2
    return 3

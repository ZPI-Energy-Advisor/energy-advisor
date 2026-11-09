"""Zmyślone definicje taryf do testów silnika (obiekty jak z bazy, z godzinami stref).

Godziny stref testowych taryf są stałe i proste (G12: dzień 6–13 i 15–22; G12w: jak G12 w dni robocze, weekendy
i święta w całości w strefie 2; G13: 7–13 i 16–21 / 13–16 i 21–22 / reszta; G14d: 7–13 / 13–16 / 16–22 / reszta),
żeby testy sprawdzały rachunek, a nie godziny konkretnego operatora.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.schemas.other import TariffTypeEnum

YEAR_2026 = (date(2026, 1, 1), date(2026, 12, 31))
ALL_DAYS = ("workday", "saturday", "sunday_holiday")


def zone_rows(zone, day_types, *intervals, season=("01-01", "12-31")):
    """Wiersze `tariff_zone_hours` strefy: przedziały w pełnych godzinach (od, do) dla rodzajów dnia i sezonu."""
    return [
        SimpleNamespace(
            zone_index=zone, day_type=day_type, season_from=season[0], season_to=season[1],
            start_minute=start * 60, end_minute=end * 60,
        )
        for day_type in day_types
        for start, end in intervals
    ]


HOURS = {
    TariffTypeEnum.G11: zone_rows(1, ALL_DAYS, (0, 24)),
    TariffTypeEnum.DYNAMIC: zone_rows(1, ALL_DAYS, (0, 24)),
    TariffTypeEnum.G12: zone_rows(1, ALL_DAYS, (6, 13), (15, 22)) + zone_rows(2, ALL_DAYS, (0, 6), (13, 15), (22, 24)),
    TariffTypeEnum.G12W: zone_rows(1, ("workday",), (6, 13), (15, 22))
    + zone_rows(2, ("workday",), (0, 6), (13, 15), (22, 24))
    + zone_rows(2, ("saturday", "sunday_holiday"), (0, 24)),
    TariffTypeEnum.G13: zone_rows(1, ALL_DAYS, (7, 13), (16, 21))
    + zone_rows(2, ALL_DAYS, (13, 16), (21, 22))
    + zone_rows(3, ALL_DAYS, (0, 7), (22, 24)),
    TariffTypeEnum.G14D: zone_rows(1, ALL_DAYS, (7, 13))
    + zone_rows(2, ALL_DAYS, (13, 16))
    + zone_rows(3, ALL_DAYS, (16, 22))
    + zone_rows(4, ALL_DAYS, (0, 7), (22, 24)),
}


def definition(code, energy, network, fixed="0", subscription="0", zones=None, valid=YEAR_2026, cycle_months=1,
               hours=None, **extra):
    """Definicja taryfy jak z bazy; strefy i stawki numerowane od 1, jak zone_index."""
    values = dict(
        tariff_code=code,
        # Oferta dynamiczna w testach domyślnie z dystrybucją G11, jak dawniej.
        distribution_group=TariffTypeEnum.G11 if code == TariffTypeEnum.DYNAMIC else code,
        name=None,
        number_of_zones=zones or len(network),
        valid_from=valid[0],
        valid_to=valid[1],
        fixed_network_fee_1phase_monthly=Decimal(fixed),
        fixed_network_fee_3phase_monthly=Decimal(fixed),
        supplier_ure_rates=[
            SimpleNamespace(zone_index=index, energy_price_per_kwh_net_pln=Decimal(rate))
            for index, rate in enumerate(energy, start=1)
        ],
        variable_network_rates=[
            SimpleNamespace(zone_index=index, rate_per_kwh_net_pln=Decimal(rate))
            for index, rate in enumerate(network, start=1)
        ],
        subscription_fees=[SimpleNamespace(billing_cycle_months=cycle_months, monthly_fee_net_pln=Decimal(subscription))],
        trade_fee_monthly=None,
        prosumer_trade_fee_monthly=None,
        zone_hours=hours if hours is not None else HOURS[code],
        energy_includes_excise=False,
        energy_price_cap_per_kwh=None,
        prosumer_margin_per_kwh=None,
        market_price_floor_mwh=None,
        market_price_cap_mwh=None,
        required_billing_cycle_months=None,
    )
    values.update(extra)
    return SimpleNamespace(**values)


def thresholds(*fees, bounds=((0, 500), (500, 1200), (1200, None))):
    return [
        SimpleNamespace(min_kwh_annual=Decimal(low), max_kwh_annual=None if high is None else Decimal(high),
                        monthly_fee_net_pln=Decimal(fee))
        for (low, high), fee in zip(bounds, fees)
    ]


def period(quality="0", renewable="0", cogeneration="0", capacity=("0", "0", "0"), transition=("0", "0", "0"),
           vat="0.23", excise="0", valid=YEAR_2026):
    return SimpleNamespace(
        valid_from=valid[0],
        valid_to=valid[1],
        quality_fee_per_kwh=Decimal(quality),
        renewable_energy_fee_per_kwh=Decimal(renewable),
        cogeneration_fee_per_kwh=Decimal(cogeneration),
        excise_per_kwh=Decimal(excise),
        vat_rate=Decimal(vat),
        capacity_thresholds=thresholds(*capacity),
        transition_thresholds=thresholds(*transition) if transition else [],
    )

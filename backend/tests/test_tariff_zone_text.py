from types import SimpleNamespace

from app.services.tariff_zone_text import describe_zones


ALL_YEAR = ("01-01", "12-31")


def _hours(zone, day_type, intervals, season=ALL_YEAR):
    return [
        SimpleNamespace(
            zone_index=zone, day_type=day_type, season_from=season[0], season_to=season[1],
            start_minute=start * 60, end_minute=end * 60,
        )
        for start, end in intervals
    ]


def _definition(rates, hours, energy=None):
    return SimpleNamespace(
        variable_network_rates=[SimpleNamespace(zone_index=zone, rate_per_kwh_net_pln=rate) for zone, rate in rates.items()],
        supplier_ure_rates=[
            SimpleNamespace(zone_index=zone, energy_price_per_kwh_net_pln=price) for zone, price in (energy or {}).items()
        ],
        zone_hours=hours,
    )


def test_single_zone_is_one_price_all_day():
    definition = _definition({1: 0.3}, [h for day in ("workday", "saturday", "sunday_holiday") for h in _hours(1, day, [(0, 24)])])

    assert describe_zones(definition) == "jedna cena przez całą dobę"


def test_cheaper_zone_hours_wrap_over_midnight():
    hours = [
        h
        for day in ("workday", "saturday", "sunday_holiday")
        for h in _hours(1, day, [(6, 13), (15, 22)]) + _hours(2, day, [(0, 6), (13, 15), (22, 24)])
    ]

    assert describe_zones(_definition({1: 0.4, 2: 0.1}, hours)) == "tańsza energia 13–15 i 22–6"


def test_whole_weekend_and_only_sundays():
    weekend = _hours(1, "workday", [(6, 13), (15, 22)]) + _hours(2, "workday", [(0, 6), (13, 15), (22, 24)])
    whole_weekend = weekend + _hours(2, "saturday", [(0, 24)]) + _hours(2, "sunday_holiday", [(0, 24)])
    only_sunday = (
        weekend + _hours(1, "saturday", [(6, 13), (15, 22)]) + _hours(2, "saturday", [(0, 6), (13, 15), (22, 24)])
        + _hours(2, "sunday_holiday", [(0, 24)])
    )

    assert describe_zones(_definition({1: 0.4, 2: 0.1}, whole_weekend)) == "tańsza energia 13–15 i 22–6 oraz cały weekend i święta"
    assert describe_zones(_definition({1: 0.4, 2: 0.1}, only_sunday)) == "tańsza energia 13–15 i 22–6 oraz całe niedziele i święta"


def test_three_zones_describe_cheapest_by_network_and_energy_price():
    winter, summer = ("10-01", "03-31"), ("04-01", "09-30")
    hours = (
        _hours(1, "workday", [(7, 13)], winter) + _hours(2, "workday", [(16, 21)], winter)
        + _hours(3, "workday", [(0, 7), (13, 16), (21, 24)], winter)
        + _hours(1, "workday", [(7, 13)], summer) + _hours(2, "workday", [(19, 22)], summer)
        + _hours(3, "workday", [(0, 7), (13, 19), (22, 24)], summer)
        + _hours(3, "saturday", [(0, 24)]) + _hours(3, "sunday_holiday", [(0, 24)])
    )
    # Sama dystrybucja strefy 1 jest najtańsza, ale z ceną energii najtańsza jest strefa 3.
    definition = _definition({1: 0.03, 2: 0.39, 3: 0.04}, hours, energy={1: 0.6, 2: 0.8, 3: 0.4})

    assert describe_zones(definition) == (
        "najtańsza energia zimą (X–III) 13–16 i 21–7, latem (IV–IX) 13–19 i 22–7 oraz cały weekend i święta"
    )


def test_minutes_are_shown_only_when_not_full_hour():
    hours = _hours(1, "workday", [(0, 22)]) + [
        SimpleNamespace(zone_index=2, day_type="workday", season_from="01-01", season_to="12-31", start_minute=22 * 60, end_minute=22 * 60 + 30),
        SimpleNamespace(zone_index=1, day_type="workday", season_from="01-01", season_to="12-31", start_minute=22 * 60 + 30, end_minute=1440),
    ]

    assert describe_zones(_definition({1: 0.4, 2: 0.1}, hours)) == "tańsza energia 22–22:30"

"""Strefy taryf z godzin w bazie: dni ustawowo wolne, rodzaje dni, sezony i doby zmiany czasu."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.schemas.calculation import CalculationDetails, TariffData
from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum
from app.services.polish_holidays import (
    SATURDAY,
    SUNDAY_HOLIDAY,
    WORKDAY,
    day_type,
    easter_sunday,
    is_public_holiday,
)
from app.services.tariff_engine import BillingContext, ZonedTariffCalculationStrategy, zone_totals
from app.services.tariff_zones import ZoneSchedule
from tariff_helpers import ALL_DAYS, HOURS, definition, period, zone_rows


YEARS = (date(2025, 1, 1), date(2026, 12, 31))
SUMMER = ("04-01", "09-30")
WINTER = ("10-01", "03-31")
# G12 jak u PGE: strefa dzienna latem 6–15 i 17–22, zimą 6–13 i 15–22; reszta doby to strefa nocna.
PGE_G12_HOURS = (
    zone_rows(1, ALL_DAYS, (6, 15), (17, 22), season=SUMMER)
    + zone_rows(2, ALL_DAYS, (0, 6), (15, 17), (22, 24), season=SUMMER)
    + zone_rows(1, ALL_DAYS, (6, 13), (15, 22), season=WINTER)
    + zone_rows(2, ALL_DAYS, (0, 6), (13, 15), (22, 24), season=WINTER)
)
# G12w: w dni robocze godziny jak G12, soboty, niedziele i święta w całości w strefie 2.
PGE_G12W_HOURS = (
    zone_rows(1, ("workday",), (6, 15), (17, 22), season=SUMMER)
    + zone_rows(2, ("workday",), (0, 6), (15, 17), (22, 24), season=SUMMER)
    + zone_rows(1, ("workday",), (6, 13), (15, 22), season=WINTER)
    + zone_rows(2, ("workday",), (0, 6), (13, 15), (22, 24), season=WINTER)
    + zone_rows(2, ("saturday", "sunday_holiday"), (0, 24))
)


def _at(day: date, clock: str) -> datetime:
    return datetime.combine(day, datetime.strptime(clock, "%H:%M").time())


def _quarters(day: date) -> list[datetime]:
    """Lokalne kwadranse doby, jak w pliku z licznika."""
    return [datetime.combine(day, datetime.min.time()) + timedelta(minutes=15 * index) for index in range(96)]


def _tariff(code=TariffTypeEnum.G12, hours=PGE_G12_HOURS, valid=YEARS):
    return definition(code, ["0.60", "0.40"], ["0", "0"], valid=valid, hours=hours)


def _schedule(code=TariffTypeEnum.G12, hours=PGE_G12_HOURS):
    return ZoneSchedule([_tariff(code, hours)])


@pytest.mark.parametrize(
    ("year", "easter"),
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))],
)
def test_easter_sunday(year, easter):
    assert easter_sunday(year) == easter


@pytest.mark.parametrize(
    "day",
    [
        date(2025, 4, 21),  # Poniedziałek Wielkanocny
        date(2026, 4, 6),
        date(2025, 6, 8),  # Zielone Świątki (niedziela, 49 dni po Wielkanocy)
        date(2026, 5, 24),
        date(2025, 6, 19),  # Boże Ciało (czwartek, 60 dni po Wielkanocy)
        date(2026, 6, 4),
        date(2026, 1, 1),
        date(2026, 1, 6),
        date(2026, 5, 1),
        date(2026, 5, 3),
        date(2026, 8, 15),
        date(2026, 11, 1),
        date(2026, 11, 11),
        date(2026, 12, 25),
        date(2026, 12, 26),
        date(2025, 12, 24),  # Wigilia — dzień wolny od 2025 r.
        date(2026, 12, 24),
    ],
)
def test_statutory_holidays_are_sunday_or_holiday_days(day):
    assert is_public_holiday(day)
    assert day_type(day) == SUNDAY_HOLIDAY


@pytest.mark.parametrize(
    "day",
    [
        date(2024, 12, 24),  # Wigilia przed 2025 r. była dniem roboczym (wtorek)
        date(2025, 6, 18),  # środa przed Bożym Ciałem
        date(2026, 6, 5),  # piątek po Bożym Ciele
        date(2026, 4, 7),  # wtorek po Poniedziałku Wielkanocnym
    ],
)
def test_days_next_to_holidays_are_workdays(day):
    assert not is_public_holiday(day)
    assert day_type(day) == WORKDAY


def test_day_types_of_a_week():
    assert day_type(date(2026, 11, 6)) == WORKDAY  # piątek
    assert day_type(date(2026, 11, 7)) == SATURDAY
    assert day_type(date(2026, 11, 8)) == SUNDAY_HOLIDAY  # niedziela


@pytest.mark.parametrize("day", [date(2026, 8, 15), date(2025, 11, 1)])
def test_holiday_on_saturday_counts_as_sunday_or_holiday(day):
    # 15.08.2026 i 1.11.2025 wypadają w sobotę
    assert day.weekday() == 5
    assert day_type(day) == SUNDAY_HOLIDAY


@pytest.mark.parametrize(
    ("moment", "zone"),
    [
        # zima: przerwa w strefie dziennej 13–15
        (_at(date(2026, 1, 14), "12:45"), 1),
        (_at(date(2026, 1, 14), "13:00"), 2),
        (_at(date(2026, 1, 14), "14:45"), 2),
        (_at(date(2026, 1, 14), "15:00"), 1),
        # lato: strefa dzienna do 15, przerwa 15–17
        (_at(date(2026, 7, 15), "12:45"), 1),
        (_at(date(2026, 7, 15), "13:00"), 1),
        (_at(date(2026, 7, 15), "14:45"), 1),
        (_at(date(2026, 7, 15), "15:00"), 2),
        (_at(date(2026, 7, 15), "16:45"), 2),
        (_at(date(2026, 7, 15), "17:00"), 1),
        # noc
        (_at(date(2026, 7, 15), "05:45"), 2),
        (_at(date(2026, 7, 15), "06:00"), 1),
        (_at(date(2026, 7, 15), "21:45"), 1),
        (_at(date(2026, 7, 15), "22:00"), 2),
    ],
)
def test_pge_g12_zone_boundaries_in_winter_and_summer(moment, zone):
    assert _schedule().zone_index(moment) == zone


@pytest.mark.parametrize(
    ("day", "zone_at_13", "zone_at_15"),
    [
        (date(2026, 3, 31), 2, 1),  # ostatni dzień zimy
        (date(2026, 4, 1), 1, 2),  # pierwszy dzień lata
        (date(2026, 9, 30), 1, 2),  # ostatni dzień lata
        (date(2026, 10, 1), 2, 1),  # pierwszy dzień zimy
        (date(2025, 12, 31), 2, 1),  # sezon zimowy przechodzi przez Nowy Rok
        (date(2026, 1, 2), 2, 1),
    ],
)
def test_season_boundaries(day, zone_at_13, zone_at_15):
    schedule = _schedule()

    assert schedule.zone_index(_at(day, "13:00")) == zone_at_13
    assert schedule.zone_index(_at(day, "15:00")) == zone_at_15


def test_g12w_saturday_and_corpus_christi_are_all_night_zone():
    schedule = _schedule(TariffTypeEnum.G12W, PGE_G12W_HOURS)
    wednesday, corpus_christi, saturday = date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 6)

    assert schedule.zone_index(_at(wednesday, "10:00")) == 1
    assert {schedule.zone_index(moment) for moment in _quarters(corpus_christi)} == {2}
    assert {schedule.zone_index(moment) for moment in _quarters(saturday)} == {2}


def test_zone_hours_come_from_definition_valid_on_reading_day():
    old = _tariff(hours=HOURS[TariffTypeEnum.G12], valid=(date(2025, 1, 1), date(2025, 12, 31)))
    new = _tariff(hours=PGE_G12_HOURS, valid=(date(2026, 1, 1), date(2026, 12, 31)))
    schedule = ZoneSchedule([new, old])

    # 2025: przerwa 13–15 przez cały rok; 2026: latem strefa dzienna do 15
    assert schedule.zone_index(_at(date(2025, 7, 15), "13:00")) == 2
    assert schedule.zone_index(_at(date(2026, 7, 15), "13:00")) == 1


def test_definitions_with_different_number_of_zones_are_rejected():
    two_zones = _tariff(valid=(date(2025, 1, 1), date(2025, 12, 31)))
    one_zone = definition(TariffTypeEnum.G12, ["0.50"], ["0"], valid=(date(2026, 1, 1), date(2026, 12, 31)),
                          hours=HOURS[TariffTypeEnum.G11])

    with pytest.raises(ValueError, match="różną liczbę stref"):
        ZoneSchedule([two_zones, one_zone])


def _bill_day(day: date, readings, schedule: ZoneSchedule):
    tariff = schedule.definitions[0]
    cycle_start = datetime(day.year, day.month, 1)
    details = CalculationDetails(
        used_energy_cycles=[(cycle_start, readings)],
        tariff_data=TariffData(
            tariff_type=tariff.tariff_code,
            billing_cycle=1,
            billing_period_start_date=cycle_start.date(),
            distribution_operator=DistributionOperatorEnum.PGE,
            phase_type="1_phase",
            contracted_power_kw=10,
        ),
    )
    context = BillingContext(
        regulatory_periods=[period(valid=YEARS)], annual_kwh=Decimal("1000"), first_day=day, last_day=day,
    )
    return ZonedTariffCalculationStrategy().calculate(details, [tariff], context, schedule).cycles[0]


def test_spring_dst_day_without_two_oclock_bills_all_energy():
    day = date(2025, 3, 30)  # doba 23-godzinna: po 01:45 jest 03:00, odczytów 02:00–02:45 nie ma
    readings = [(moment, 1.0) for moment in _quarters(day) if moment.hour != 2]
    schedule = _schedule()

    cycle = _bill_day(day, readings, schedule)

    # zima (do 31.03): strefa 1 = 6–13 i 15–22 (56 kwadransów); strefa 2 = 0–6 bez godziny 2 (20), 13–15 (8), 22–24 (8)
    assert zone_totals(readings, schedule) == [56, 36]
    assert cycle.active_energy_kwh == Decimal("92")  # 23 h × 4 kwadranse
    assert cycle.active_energy_net == Decimal("48.00")  # 56 × 0,60 + 36 × 0,40 = 33,60 + 14,40


def test_autumn_dst_day_bills_repeated_hour_in_its_zone():
    day = date(2025, 10, 26)  # doba 25-godzinna: oba wystąpienia 02:00–02:45 zsumowane w jednym lokalnym kwadransie
    readings = [(moment, 2.0 if moment.hour == 2 else 1.0) for moment in _quarters(day)]
    schedule = _schedule()

    cycle = _bill_day(day, readings, schedule)

    # zima: strefa 2 = 0–6 (24 kwadranse, w tym 4 podwójne = 28 kWh) + 13–15 (8) + 22–24 (8) = 44 kWh
    assert zone_totals(readings, schedule) == [56, 44]
    assert cycle.active_energy_kwh == Decimal("100")  # 25 h × 4 kwadranse × 1 kWh
    assert cycle.active_energy_net == Decimal("51.20")  # 56 × 0,60 + 44 × 0,40 = 33,60 + 17,60


@pytest.mark.parametrize(
    ("hours", "moment"),
    [
        # godziny tylko dla dni roboczych, a odczyt w sobotę
        (zone_rows(1, ("workday",), (6, 22)) + zone_rows(2, ("workday",), (0, 6), (22, 24)), _at(date(2026, 11, 7), "10:00")),
        # godziny tylko na lato, a odczyt zimą
        (zone_rows(1, ALL_DAYS, (6, 22), season=SUMMER) + zone_rows(2, ALL_DAYS, (0, 6), (22, 24), season=SUMMER),
         _at(date(2026, 1, 14), "10:00")),
    ],
)
def test_day_without_zone_hours_is_rejected_with_clear_error(hours, moment):
    with pytest.raises(ValueError, match=f"Taryfa G12 nie ma godzin stref dla dnia {moment.date().isoformat()}"):
        _schedule(hours=hours).zone_index(moment)


def test_hour_outside_every_zone_is_rejected_with_clear_error():
    with_gap = zone_rows(1, ALL_DAYS, (6, 22)) + zone_rows(2, ALL_DAYS, (0, 5), (22, 24))

    with pytest.raises(ValueError, match="Godzina 05:00 dnia 2026-11-06 nie należy do żadnej strefy taryfy G12"):
        _schedule(hours=with_gap).zone_index(_at(date(2026, 11, 6), "05:00"))


def test_day_outside_definitions_is_rejected_with_clear_error():
    with pytest.raises(ValueError, match="Brak stawek taryfy G12 dla dnia 2027-01-01"):
        _schedule().zone_index(_at(date(2027, 1, 1), "10:00"))

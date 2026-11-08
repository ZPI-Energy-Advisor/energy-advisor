"""Dni ustawowo wolne od pracy w Polsce i rodzaj dnia dla godzin stref taryf.

Ustawa z 18 stycznia 1951 r. o dniach wolnych od pracy: 1 i 6 stycznia, Wielkanoc i Poniedziałek Wielkanocny,
1 i 3 maja, Zielone Świątki (niedziela, 49 dni po Wielkanocy), Boże Ciało (czwartek, 60 dni po Wielkanocy),
15 sierpnia, 1 i 11 listopada, 25 i 26 grudnia; od 2025 r. także Wigilia (24 grudnia). Taryfy OSD traktują
niedziele i te dni jednakowo („niedziele i święta”), a święto w sobotę też jest dniem świątecznym.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

WORKDAY = "workday"
SATURDAY = "saturday"
SUNDAY_HOLIDAY = "sunday_holiday"
# Pierwszy rok, w którym Wigilia jest dniem ustawowo wolnym od pracy.
CHRISTMAS_EVE_FROM_YEAR = 2025


def easter_sunday(year: int) -> date:
    """Wielkanoc w kalendarzu gregoriańskim (algorytm Meeusa/Jonesa/Butchera)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    weekday_offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_offset) // 451
    month, day = divmod(h + weekday_offset - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=None)
def public_holidays(year: int) -> frozenset[date]:
    easter = easter_sunday(year)
    days = {
        date(year, 1, 1),
        date(year, 1, 6),
        easter,
        easter + timedelta(days=1),
        date(year, 5, 1),
        date(year, 5, 3),
        easter + timedelta(days=49),
        easter + timedelta(days=60),
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    if year >= CHRISTMAS_EVE_FROM_YEAR:
        days.add(date(year, 12, 24))
    return frozenset(days)


def is_public_holiday(day: date) -> bool:
    return day in public_holidays(day.year)


def day_type(day: date) -> str:
    """Rodzaj dnia w godzinach stref: niedziela lub święto, sobota albo dzień roboczy."""
    if day.weekday() == 6 or is_public_holiday(day):
        return SUNDAY_HOLIDAY
    if day.weekday() == 5:
        return SATURDAY
    return WORKDAY

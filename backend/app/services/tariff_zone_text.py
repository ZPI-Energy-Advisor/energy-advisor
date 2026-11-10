"""Krótki opis stref taryfy do formularza profilu, np. „tańsza energia 13–15 i 22–6 oraz cały weekend”."""

from app.models.NewModels import TariffDefinition

DAY_MINUTES = 1440
WEEKEND_DAYS = ("saturday", "sunday_holiday")
ROMAN_MONTHS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")


def _clock(minute: int) -> str:
    return str(minute // 60) if minute % 60 == 0 else f"{minute // 60}:{minute % 60:02d}"


def _merged(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Łączy stykające się przedziały; przedział kończący dobę łączy się z zaczynającym kolejną (22–24 i 0–6 → 22–6)."""
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and merged[-1][1] >= start:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    if len(merged) > 1 and merged[0][0] == 0 and merged[-1][1] == DAY_MINUTES:
        merged[-1][1] = merged.pop(0)[1]
    return [(start, end) for start, end in merged]


def _hours_text(intervals: list[tuple[int, int]]) -> str:
    return " i ".join(f"{_clock(start)}–{_clock(end % DAY_MINUTES)}" for start, end in intervals)


def _is_whole_day(intervals: list[tuple[int, int]]) -> bool:
    return intervals == [(0, DAY_MINUTES)]


def _is_winter(season_from: str, season_to: str) -> bool:
    # Sezon obejmujący styczeń to zima (np. X–III), pozostałe to lato (np. IV–IX).
    return season_from > season_to or season_from[:2] == "01"


def _season_label(season_from: str, season_to: str) -> str:
    months = f"{ROMAN_MONTHS[int(season_from[:2]) - 1]}–{ROMAN_MONTHS[int(season_to[:2]) - 1]}"
    return f"{'zimą' if _is_winter(season_from, season_to) else 'latem'} ({months})"


def _zone_price(definition: TariffDefinition, zone_index: int) -> float:
    network = {rate.zone_index: float(rate.rate_per_kwh_net_pln) for rate in definition.variable_network_rates}
    energy = {rate.zone_index: float(rate.energy_price_per_kwh_net_pln) for rate in definition.supplier_ure_rates}
    return network.get(zone_index, 0.0) + energy.get(zone_index, 0.0)


def describe_zones(definition: TariffDefinition) -> str | None:
    zones = sorted({hour.zone_index for hour in definition.zone_hours})
    if not zones:
        return None
    if len(zones) == 1:
        return "jedna cena przez całą dobę"

    cheapest = min(zones, key=lambda zone: _zone_price(definition, zone))
    by_season_and_day: dict[tuple[str, str], dict[str, list[tuple[int, int]]]] = {}
    for hour in definition.zone_hours:
        if hour.zone_index != cheapest:
            continue
        days = by_season_and_day.setdefault((hour.season_from, hour.season_to), {})
        days.setdefault(hour.day_type, []).append((hour.start_minute, hour.end_minute))

    workday_texts = []
    weekend = set()
    for (season_from, season_to), days in sorted(by_season_and_day.items(), key=lambda item: not _is_winter(*item[0])):
        workday = _merged(days.get("workday", []))
        if workday:
            workday_texts.append(((season_from, season_to), _hours_text(workday)))
        for day in WEEKEND_DAYS:
            if _is_whole_day(_merged(days.get(day, []))) and not _is_whole_day(workday):
                weekend.add(day)

    label = "tańsza energia" if len(zones) == 2 else "najtańsza energia"
    if len({text for _, text in workday_texts}) <= 1:
        text = f"{label} {workday_texts[0][1]}" if workday_texts else label
    else:
        text = f"{label} " + ", ".join(f"{_season_label(*season)} {hours}" for season, hours in workday_texts)
    if weekend == set(WEEKEND_DAYS):
        text += " oraz cały weekend i święta"
    elif weekend == {"sunday_holiday"}:
        text += " oraz całe niedziele i święta"
    return text

"""Odczyt i walidacja plików cennika (`backend/data/tariffs/<rok>/<operator>.json`, `regulatory.json`).

Format opisuje `docs/tariff-data-format.md`. Błędy zbieramy wszystkie naraz i podajemy z miejscem w pliku,
żeby poprawka danych nie wymagała wielu przebiegów.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.schemas.other import DistributionOperatorEnum, TariffTypeEnum


DAY_TYPES = ("workday", "saturday", "sunday_holiday")
DAY_TYPE_NAMES = {"workday": "dni robocze", "saturday": "soboty", "sunday_holiday": "niedziele i święta"}
BILLING_CYCLES = (1, 2, 6, 12)
MINUTES_PER_DAY = 24 * 60
WHOLE_YEAR = ("01-01", "12-31")
# Rok przestępny do wyliczania dni roku MM-DD razem z 29 lutego.
_LEAP_YEAR = 2024
_MAX_HOUR_ERRORS = 6
REGULATORY_FILE_NAME = "regulatory.json"


class TariffDataError(Exception):
    """Błędy danych cennika; `errors` to lista komunikatów po polsku."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


# ---------------------------------------------------------------- model pliku


@dataclass(frozen=True)
class Document:
    key: str
    title: str
    url: str | None = None


@dataclass(frozen=True)
class Source:
    """Dokument i strona, z których pochodzi wartość, i/lub opis, skąd ją przyjęto."""

    doc: str | None
    page: str | None
    text: str | None = None

    def describe(self, documents: dict[str, Document]) -> str:
        reference = None
        if self.doc is not None:
            title = documents[self.doc].title
            reference = f"{title}, {self.page}" if self.page else title
        if self.text:
            return f"{self.text} (podstawa: {reference})" if reference else self.text
        return str(reference)


@dataclass(frozen=True)
class HourRule:
    zone: int
    day_types: tuple[str, ...]
    season: tuple[str, str]
    intervals: tuple[tuple[int, int], ...]


@dataclass
class DistributionTariff:
    code: TariffTypeEnum
    zone_names: dict[int, str]
    rates: dict[int, Decimal]
    fixed_1phase: Decimal
    fixed_3phase: Decimal
    rates_source: Source
    hours: list[HourRule]
    hours_source: Source
    subscription: dict[int, Decimal] | None = None
    subscription_source: Source | None = None


@dataclass
class DistributionEntry:
    index: int
    valid_from: date
    valid_to: date
    subscription: dict[int, Decimal]
    subscription_source: Source | None
    tariffs: dict[TariffTypeEnum, DistributionTariff]
    note: str | None = None

    def subscription_for(self, code: TariffTypeEnum) -> tuple[dict[int, Decimal], Source | None]:
        tariff = self.tariffs[code]
        if tariff.subscription is not None:
            return tariff.subscription, tariff.subscription_source
        return self.subscription, self.subscription_source


@dataclass
class EnergyTariff:
    code: TariffTypeEnum
    prices: dict[int, Decimal]
    source: Source | None = None


@dataclass
class EnergyEntry:
    index: int
    valid_from: date
    valid_to: date
    seller: str
    includes_excise: bool
    excise_source: Source
    price_cap: Decimal | None
    price_cap_source: Source | None
    trade_fee: Decimal | None
    trade_fee_source: Source | None
    source: Source
    tariffs: dict[TariffTypeEnum, EnergyTariff]
    note: str | None = None


@dataclass
class DynamicOffer:
    index: int
    valid_from: date
    valid_to: date
    seller: str
    name: str
    # Grupy dystrybucyjne, z którymi sprzedawca dopuszcza ofertę (dystrybucja według grupy klienta).
    distribution_tariffs: tuple[TariffTypeEnum, ...]
    billing_cycle_months: int
    margin: Decimal
    prosumer_margin: Decimal | None
    trade_fee_monthly: Decimal
    prosumer_trade_fee_monthly: Decimal | None
    market_price_floor: Decimal | None
    market_price_cap: Decimal | None
    includes_excise: bool
    source: Source
    field_sources: dict[str, Source] = field(default_factory=dict)
    note: str | None = None


@dataclass
class UnsupportedEntry:
    index: int
    code: str
    name: str
    valid_from: date
    valid_to: date
    reason: str
    source: Source


@dataclass
class OperatorFile:
    path: Path
    operator: DistributionOperatorEnum
    year: int
    covers_from: date
    covers_to: date
    documents: dict[str, Document]
    distribution: list[DistributionEntry]
    energy: list[EnergyEntry]
    dynamic_offers: list[DynamicOffer]
    unsupported: list[UnsupportedEntry]
    notes: list[str]


@dataclass(frozen=True)
class FeeBand:
    min_kwh: Decimal
    max_kwh: Decimal | None
    fee: Decimal


@dataclass
class RegulatoryEntry:
    index: int
    valid_from: date
    valid_to: date
    values: dict[str, tuple[Decimal, Source]]
    capacity_bands: list[FeeBand]
    capacity_source: Source
    transition_bands: list[FeeBand]
    transition_source: Source | None


@dataclass
class RegulatoryFile:
    path: Path
    year: int
    covers_from: date
    covers_to: date
    documents: dict[str, Document]
    periods: list[RegulatoryEntry]


REGULATORY_VALUES = {
    "quality_fee_per_kwh": "stawka jakościowa",
    "renewable_fee_per_kwh": "opłata OZE",
    "cogeneration_fee_per_kwh": "opłata kogeneracyjna",
    "excise_per_kwh": "akcyza",
    "vat_rate": "VAT",
}


# ---------------------------------------------------------------- pomocnicze


def season_contains(season: tuple[str, str], month_day: str) -> bool:
    """Czy dzień roku `MM-DD` należy do sezonu; sezon może przechodzić przez Nowy Rok (np. 10-01–03-31)."""
    first, last = season
    if first <= last:
        return first <= month_day <= last
    return month_day >= first or month_day <= last


def days_between(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def format_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _overlap(first: tuple[date, date], second: tuple[date, date]) -> bool:
    return first[0] <= second[1] and second[0] <= first[1]


def _range(item) -> str:
    return f"{item.valid_from.isoformat()} – {item.valid_to.isoformat()}"


class _Reader:
    """Zbiera błędy z miejscem w pliku i odczytuje pola z kontrolą typów."""

    TIME = re.compile(r"^(\d{2}):(\d{2})$")
    MONTH_DAY = re.compile(r"^(\d{2})-(\d{2})$")

    def __init__(self, path: Path):
        self.path = path
        self.errors: list[str] = []
        self.documents: dict[str, Document] = {}

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{self.path.parent.name}/{self.path.name}: {where}: {message}")

    def require(self, data: dict, key: str, where: str) -> Any:
        if not isinstance(data, dict):
            self.error(where, "oczekiwano obiektu JSON.")
            return None
        if key not in data or data[key] is None:
            self.error(where, f"brak pola „{key}”.")
            return None
        return data[key]

    def text(self, data: dict, key: str, where: str, optional: bool = False) -> str | None:
        value = data.get(key) if optional else self.require(data, key, where)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            self.error(where, f"pole „{key}” musi być niepustym tekstem.")
            return None
        return value.strip()

    def day(self, data: dict, key: str, where: str) -> date | None:
        value = self.require(data, key, where)
        if value is None:
            return None
        try:
            if not isinstance(value, str) or len(value) != 10:
                raise ValueError
            return date.fromisoformat(value)
        except ValueError:
            self.error(where, f"pole „{key}”: „{value}” nie jest datą RRRR-MM-DD.")
            return None

    def decimal(self, value: Any, where: str, *, allow_negative: bool = False) -> Decimal | None:
        if not isinstance(value, str):
            self.error(where, f"kwota „{value}” musi być napisem dziesiętnym, np. \"0.3469\".")
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            self.error(where, f"„{value}” nie jest liczbą dziesiętną.")
            return None
        if not number.is_finite() or (number < 0 and not allow_negative):
            self.error(where, f"„{value}” musi być skończoną liczbą nieujemną.")
            return None
        return number

    def field_decimal(self, data: dict, key: str, where: str, *, optional: bool = False,
                      allow_negative: bool = False) -> Decimal | None:
        value = data.get(key) if optional else self.require(data, key, where)
        if value is None:
            return None
        return self.decimal(value, f"{where}, pole „{key}”", allow_negative=allow_negative)

    def boolean(self, data: dict, key: str, where: str) -> bool | None:
        value = self.require(data, key, where)
        if value is None:
            return None
        if not isinstance(value, bool):
            self.error(where, f"pole „{key}” musi być true albo false.")
            return None
        return value

    def zone_key(self, key: Any, where: str) -> int | None:
        if not isinstance(key, str) or key not in {"1", "2", "3", "4"}:
            self.error(where, f"numer strefy „{key}” musi być napisem od \"1\" do \"4\".")
            return None
        return int(key)

    def cycles(self, data: Any, where: str) -> dict[int, Decimal] | None:
        if not isinstance(data, dict) or not data:
            self.error(where, "oczekiwano obiektu {okres w miesiącach: opłata}.")
            return None
        fees = {}
        for key, value in data.items():
            if key not in {str(months) for months in BILLING_CYCLES}:
                self.error(where, f"okres rozliczeniowy „{key}” musi być jednym z 1, 2, 6, 12.")
                continue
            fee = self.decimal(value, f"{where}, okres {key}")
            if fee is not None:
                fees[int(key)] = fee
        return fees

    def source(self, data: Any, where: str, *, optional: bool = False) -> Source | None:
        if data is None:
            if not optional:
                self.error(where, "brak źródła (dokument i strona albo opis).")
            return None
        if not isinstance(data, dict):
            self.error(where, "źródło musi być obiektem {\"doc\": …, \"page\": …}.")
            return None
        doc = data.get("doc")
        page = data.get("page")
        text = data.get("text")
        if doc is not None and doc not in self.documents:
            self.error(where, f"źródło wskazuje nieznany dokument „{doc}”.")
            doc = None
        page = page.strip() if isinstance(page, str) and page.strip() else None
        if isinstance(text, str) and text.strip():
            # Wartość przyjęta bez dokumentu wprost (np. z wcześniejszej wersji cennika): opis + ewentualna podstawa.
            return Source(doc=doc, page=page, text=text.strip())
        if doc is None or page is None:
            self.error(where, "źródło musi mieć dokument („doc”) i stronę („page”) albo opis („text”).")
            return None
        return Source(doc=doc, page=page)

    def tariff_code(self, value: Any, where: str) -> TariffTypeEnum | None:
        if not isinstance(value, str):
            self.error(where, "kod taryfy musi być tekstem.")
            return None
        try:
            code = TariffTypeEnum.from_code(value)
        except ValueError:
            self.error(
                where,
                f"nieznany kod taryfy „{value}” — dodaj go do TariffTypeEnum albo wpisz taryfę do „unsupported”.",
            )
            return None
        if code == TariffTypeEnum.DYNAMIC:
            self.error(where, "oferty z ceną dynamiczną wpisuje się w „dynamic_offers”.")
            return None
        return code

    def minutes(self, value: Any, where: str, *, end: bool) -> int | None:
        match = self.TIME.match(value) if isinstance(value, str) else None
        if match is None:
            self.error(where, f"godzina „{value}” musi mieć format HH:MM.")
            return None
        hours, minutes = int(match.group(1)), int(match.group(2))
        total = hours * 60 + minutes
        if minutes > 59 or total > MINUTES_PER_DAY or (total == MINUTES_PER_DAY and not end):
            self.error(where, f"nieprawidłowa godzina „{value}”.")
            return None
        return total

    def month_day(self, value: Any, where: str) -> str | None:
        match = self.MONTH_DAY.match(value) if isinstance(value, str) else None
        if match is None:
            self.error(where, f"dzień sezonu „{value}” musi mieć format MM-DD.")
            return None
        try:
            date(_LEAP_YEAR, int(match.group(1)), int(match.group(2)))
        except ValueError:
            self.error(where, f"nie ma dnia „{value}”.")
            return None
        return value

    def documents_section(self, data: dict) -> dict[str, Document]:
        raw = self.require(data, "documents", "documents")
        documents = {}
        if not isinstance(raw, dict) or not raw:
            self.error("documents", "oczekiwano niepustego obiektu {klucz: dokument}.")
            return documents
        for key, item in raw.items():
            where = f"documents.{key}"
            if not isinstance(item, dict):
                self.error(where, "oczekiwano obiektu z tytułem dokumentu.")
                continue
            title = self.text(item, "title", where)
            if title:
                documents[key] = Document(
                    key=key,
                    title=title,
                    url=self.text(item, "url", where, optional=True),
                )
        return documents

    def covers(self, data: dict) -> tuple[date | None, date | None]:
        covers = self.require(data, "covers", "covers")
        if not isinstance(covers, dict):
            return None, None
        first, last = self.day(covers, "from", "covers"), self.day(covers, "to", "covers")
        if first and last and first > last:
            self.error("covers", "początek zakresu jest późniejszy niż koniec.")
        return first, last

    def period(self, data: dict, where: str, covers: tuple[date | None, date | None]) -> tuple[date | None, date | None]:
        first, last = self.day(data, "valid_from", where), self.day(data, "valid_to", where)
        if first and last:
            if first > last:
                self.error(where, "valid_from jest późniejsze niż valid_to.")
            elif covers[0] and covers[1] and (first < covers[0] or last > covers[1]):
                self.error(
                    where,
                    f"okres {first.isoformat()} – {last.isoformat()} wychodzi poza zakres pliku "
                    f"{covers[0].isoformat()} – {covers[1].isoformat()}.",
                )
        return first, last


# ---------------------------------------------------------------- plik operatora


def _parse_hours(reader: _Reader, raw: Any, where: str) -> list[HourRule]:
    rules = []
    if not isinstance(raw, list) or not raw:
        reader.error(where, "pole „hours” musi być niepustą listą reguł godzin.")
        return rules
    for number, item in enumerate(raw):
        rule_where = f"{where}.hours[{number}]"
        if not isinstance(item, dict):
            reader.error(rule_where, "oczekiwano obiektu reguły.")
            continue
        zone = reader.zone_key(reader.require(item, "zone", rule_where), rule_where)
        days = item.get("days")
        if days == "all":
            day_types = DAY_TYPES
        elif isinstance(days, list) and days and all(day in DAY_TYPES for day in days) and len(set(days)) == len(days):
            day_types = tuple(day for day in DAY_TYPES if day in days)
        else:
            reader.error(rule_where, f"„days” musi być \"all\" albo listą z {', '.join(DAY_TYPES)}.")
            continue
        season_raw = item.get("season")
        if season_raw == "all":
            season = WHOLE_YEAR
        elif isinstance(season_raw, list) and len(season_raw) == 2:
            first = reader.month_day(season_raw[0], rule_where)
            last = reader.month_day(season_raw[1], rule_where)
            if first is None or last is None:
                continue
            season = (first, last)
        else:
            reader.error(rule_where, "„season” musi być \"all\" albo [\"MM-DD\", \"MM-DD\"].")
            continue
        intervals = []
        raw_intervals = item.get("intervals")
        if not isinstance(raw_intervals, list) or not raw_intervals:
            reader.error(rule_where, "„intervals” musi być niepustą listą [\"HH:MM\", \"HH:MM\"].")
            continue
        for interval in raw_intervals:
            if not isinstance(interval, list) or len(interval) != 2:
                reader.error(rule_where, f"przedział {interval} musi mieć postać [\"HH:MM\", \"HH:MM\"].")
                continue
            start = reader.minutes(interval[0], rule_where, end=False)
            end = reader.minutes(interval[1], rule_where, end=True)
            if start is None or end is None:
                continue
            if start >= end:
                reader.error(rule_where, f"przedział {interval[0]}–{interval[1]} musi kończyć się po początku.")
                continue
            intervals.append((start, end))
        if zone is not None and intervals:
            rules.append(HourRule(zone=zone, day_types=day_types, season=season, intervals=tuple(intervals)))
    return rules


def _parse_distribution(reader: _Reader, raw: Any, covers) -> list[DistributionEntry]:
    entries = []
    if not isinstance(raw, list):
        reader.error("distribution", "oczekiwano listy wpisów taryfy OSD.")
        return entries
    for index, item in enumerate(raw):
        where = f"distribution[{index}]"
        if not isinstance(item, dict):
            reader.error(where, "oczekiwano obiektu wpisu.")
            continue
        first, last = reader.period(item, where, covers)
        subscription = reader.cycles(reader.require(item, "subscription", where), f"{where}.subscription") or {}
        subscription_source = reader.source(item.get("subscription_source"), f"{where}.subscription_source")
        tariffs = {}
        raw_tariffs = reader.require(item, "tariffs", where)
        if not isinstance(raw_tariffs, dict) or not raw_tariffs:
            reader.error(where, "„tariffs” musi być niepustym obiektem {kod taryfy: stawki}.")
            raw_tariffs = {}
        for code_text, data in raw_tariffs.items():
            tariff_where = f"{where}.tariffs.{code_text}"
            code = reader.tariff_code(code_text, tariff_where)
            if code is None:
                continue
            if code in tariffs:
                reader.error(tariff_where, f"taryfa {code.value} występuje we wpisie dwa razy.")
                continue
            if not isinstance(data, dict):
                reader.error(tariff_where, "oczekiwano obiektu stawek taryfy.")
                continue
            zone_names, rates = {}, {}
            raw_zones = reader.require(data, "zones", tariff_where)
            if not isinstance(raw_zones, dict) or not raw_zones:
                reader.error(tariff_where, "„zones” musi być niepustym obiektem {strefa: {name, rate}}.")
                raw_zones = {}
            for key, zone_data in raw_zones.items():
                zone = reader.zone_key(key, tariff_where)
                if zone is None:
                    continue
                if not isinstance(zone_data, dict):
                    reader.error(tariff_where, f"strefa {key}: oczekiwano {{\"name\": …, \"rate\": …}}.")
                    continue
                zone_names[zone] = reader.text(zone_data, "name", f"{tariff_where}.zones.{key}") or f"strefa {zone}"
                rate = reader.field_decimal(zone_data, "rate", f"{tariff_where}.zones.{key}")
                if rate is not None:
                    rates[zone] = rate
            if rates and sorted(rates) != list(range(1, len(rates) + 1)):
                reader.error(tariff_where, "strefy muszą być numerowane kolejno od 1.")
            fixed = reader.require(data, "fixed_monthly", tariff_where)
            fixed_1phase = fixed_3phase = None
            if isinstance(fixed, dict):
                fixed_1phase = reader.field_decimal(fixed, "1f", f"{tariff_where}.fixed_monthly")
                fixed_3phase = reader.field_decimal(fixed, "3f", f"{tariff_where}.fixed_monthly")
            elif fixed is not None:
                reader.error(tariff_where, "„fixed_monthly” musi mieć pola \"1f\" i \"3f\".")
            rates_source = reader.source(data.get("rates_source"), f"{tariff_where}.rates_source")
            hours = _parse_hours(reader, data.get("hours"), tariff_where)
            hours_source = reader.source(data.get("hours_source"), f"{tariff_where}.hours_source")
            own_subscription = None
            own_subscription_source = None
            if data.get("subscription") is not None:
                own_subscription = reader.cycles(data["subscription"], f"{tariff_where}.subscription")
                own_subscription_source = reader.source(
                    data.get("subscription_source"), f"{tariff_where}.subscription_source"
                )
            candidate = DistributionTariff(
                code=code,
                zone_names=zone_names,
                rates=rates,
                fixed_1phase=fixed_1phase,
                fixed_3phase=fixed_3phase,
                rates_source=rates_source,
                hours=hours,
                hours_source=hours_source,
                subscription=own_subscription,
                subscription_source=own_subscription_source,
            )
            # Godziny sprawdzamy także wtedy, gdy inne pole taryfy ma błąd — wszystkie błędy w jednym przebiegu.
            if rates and hours:
                _check_hours(reader, candidate, tariff_where)
            if None in (fixed_1phase, fixed_3phase, rates_source, hours_source) or not rates:
                continue
            tariffs[code] = candidate
        if first and last:
            entries.append(
                DistributionEntry(
                    index=index,
                    valid_from=first,
                    valid_to=last,
                    subscription=subscription,
                    subscription_source=subscription_source,
                    tariffs=tariffs,
                    note=item.get("note"),
                )
            )
    return entries


def _check_hours(reader: _Reader, tariff: DistributionTariff, where: str) -> None:
    """Godziny taryfy dla każdego rodzaju dnia i dnia roku pokrywają dobę bez dziur i nakładania."""
    used = {rule.zone for rule in tariff.hours}
    for zone in sorted(set(tariff.rates) - used):
        reader.error(where, f"strefa {zone} ma stawki, ale nie ma godzin.")
    for zone in sorted(used - set(tariff.rates)):
        reader.error(where, f"godziny strefy {zone}, która nie ma stawek.")

    # Dni roku z tym samym zestawem reguł sezonowych sprawdzamy raz, podając pierwszy taki dzień.
    signatures: dict[tuple[int, ...], str] = {}
    current = date(_LEAP_YEAR, 1, 1)
    while current.year == _LEAP_YEAR:
        month_day = current.strftime("%m-%d")
        signature = tuple(
            number for number, rule in enumerate(tariff.hours) if season_contains(rule.season, month_day)
        )
        signatures.setdefault(signature, month_day)
        current += timedelta(days=1)

    found = 0
    for signature, month_day in signatures.items():
        for day_type in DAY_TYPES:
            intervals = sorted(
                (start, end, tariff.hours[number].zone)
                for number in signature
                if day_type in tariff.hours[number].day_types
                for start, end in tariff.hours[number].intervals
            )
            cursor = 0
            problems = []
            for start, end, _zone in intervals:
                if start > cursor:
                    problems.append(f"brak strefy {format_minutes(cursor)}–{format_minutes(start)}")
                elif start < cursor:
                    problems.append(
                        f"strefy nakładają się {format_minutes(start)}–{format_minutes(min(end, cursor))}"
                    )
                cursor = max(cursor, end)
            if cursor < MINUTES_PER_DAY:
                problems.append(f"brak strefy {format_minutes(cursor)}–24:00")
            for problem in problems:
                found += 1
                if found <= _MAX_HOUR_ERRORS:
                    reader.error(
                        where,
                        f"godziny {tariff.code.value}: {DAY_TYPE_NAMES[day_type]}, dzień {month_day}: {problem}.",
                    )


def _parse_energy(reader: _Reader, raw: Any, covers) -> list[EnergyEntry]:
    entries = []
    if not isinstance(raw, list):
        reader.error("energy", "oczekiwano listy wpisów taryfy sprzedawcy.")
        return entries
    for index, item in enumerate(raw):
        where = f"energy[{index}]"
        if not isinstance(item, dict):
            reader.error(where, "oczekiwano obiektu wpisu.")
            continue
        first, last = reader.period(item, where, covers)
        seller = reader.text(item, "seller", where)
        includes_excise = reader.boolean(item, "prices_include_excise", where)
        excise_source = reader.source(item.get("excise_source"), f"{where}.excise_source")
        price_cap = reader.field_decimal(item, "price_cap", where, optional=True)
        price_cap_source = reader.source(
            item.get("price_cap_source"), f"{where}.price_cap_source", optional=price_cap is None
        )
        # Opłata handlowa sprzedawcy, zł/mies. netto (taryfy URE zwykle jej nie mają).
        trade_fee = reader.field_decimal(item, "trade_fee_monthly", where, optional=True)
        trade_fee_source = reader.source(
            item.get("trade_fee_source"), f"{where}.trade_fee_source", optional=trade_fee is None
        )
        source = reader.source(item.get("source"), f"{where}.source")
        tariffs = {}
        raw_tariffs = reader.require(item, "tariffs", where)
        if not isinstance(raw_tariffs, dict) or not raw_tariffs:
            reader.error(where, "„tariffs” musi być niepustym obiektem {kod taryfy: {zones: …}}.")
            raw_tariffs = {}
        for code_text, data in raw_tariffs.items():
            tariff_where = f"{where}.tariffs.{code_text}"
            code = reader.tariff_code(code_text, tariff_where)
            if code is None or not isinstance(data, dict):
                if code is not None:
                    reader.error(tariff_where, "oczekiwano obiektu {\"zones\": {strefa: cena}}.")
                continue
            prices = {}
            raw_zones = reader.require(data, "zones", tariff_where)
            if not isinstance(raw_zones, dict) or not raw_zones:
                reader.error(tariff_where, "„zones” musi być niepustym obiektem {strefa: cena}.")
                raw_zones = {}
            for key, value in raw_zones.items():
                zone = reader.zone_key(key, tariff_where)
                price = reader.decimal(value, f"{tariff_where}.zones.{key}")
                if zone is not None and price is not None:
                    prices[zone] = price
            own_source = reader.source(data.get("source"), f"{tariff_where}.source", optional=True)
            if prices:
                tariffs[code] = EnergyTariff(code=code, prices=prices, source=own_source)
        if first and last and seller and includes_excise is not None and excise_source and source:
            entries.append(
                EnergyEntry(
                    index=index,
                    valid_from=first,
                    valid_to=last,
                    seller=seller,
                    includes_excise=includes_excise,
                    excise_source=excise_source,
                    price_cap=price_cap,
                    price_cap_source=price_cap_source,
                    trade_fee=trade_fee,
                    trade_fee_source=trade_fee_source,
                    source=source,
                    tariffs=tariffs,
                    note=item.get("note"),
                )
            )
    return entries


DYNAMIC_FIELDS = (
    "margin", "prosumer_margin", "trade_fee_monthly", "prosumer_trade_fee_monthly",
    "market_price_floor", "market_price_cap", "billing_cycle_months", "prices_include_excise", "valid_from",
)


def _parse_dynamic(reader: _Reader, raw: Any, covers) -> list[DynamicOffer]:
    offers = []
    if raw is None:
        return offers
    if not isinstance(raw, list):
        reader.error("dynamic_offers", "oczekiwano listy ofert.")
        return offers
    for index, item in enumerate(raw):
        where = f"dynamic_offers[{index}]"
        if not isinstance(item, dict):
            reader.error(where, "oczekiwano obiektu oferty.")
            continue
        first, last = reader.period(item, where, covers)
        seller = reader.text(item, "seller", where)
        name = reader.text(item, "name", where)
        raw_groups = reader.require(item, "distribution_tariffs", where)
        distribution_tariffs = None
        if raw_groups is not None:
            if not isinstance(raw_groups, list) or not raw_groups:
                reader.error(where, "„distribution_tariffs” musi być niepustą listą grup, np. [\"G11\", \"G12\"].")
            else:
                codes = [reader.tariff_code(code, where) for code in raw_groups]
                if None not in codes:
                    if TariffTypeEnum.DYNAMIC in codes or len(set(codes)) != len(codes):
                        reader.error(where, "„distribution_tariffs” zawiera „dynamic” albo powtórzoną grupę.")
                    else:
                        distribution_tariffs = tuple(codes)
        cycle = reader.require(item, "billing_cycle_months", where)
        if cycle is not None and cycle not in BILLING_CYCLES:
            reader.error(where, "„billing_cycle_months” musi być jednym z 1, 2, 6, 12.")
            cycle = None
        margin = reader.field_decimal(item, "margin", where, allow_negative=True)
        prosumer_margin = reader.field_decimal(item, "prosumer_margin", where, optional=True, allow_negative=True)
        trade_fee = reader.field_decimal(item, "trade_fee_monthly", where)
        prosumer_trade_fee = reader.field_decimal(item, "prosumer_trade_fee_monthly", where, optional=True)
        floor = reader.field_decimal(item, "market_price_floor", where, optional=True, allow_negative=True)
        cap = reader.field_decimal(item, "market_price_cap", where, optional=True, allow_negative=True)
        if floor is not None and cap is not None and floor > cap:
            reader.error(where, "„market_price_floor” jest większe niż „market_price_cap”.")
        includes_excise = reader.boolean(item, "prices_include_excise", where)
        source = reader.source(item.get("source"), f"{where}.source")
        field_sources = {}
        raw_field_sources = item.get("field_sources") or {}
        if not isinstance(raw_field_sources, dict):
            reader.error(where, "„field_sources” musi być obiektem {pole: źródło}.")
            raw_field_sources = {}
        for field_name, raw_source in raw_field_sources.items():
            if field_name not in DYNAMIC_FIELDS:
                reader.error(where, f"„field_sources”: nieznane pole „{field_name}”.")
                continue
            field_source = reader.source(raw_source, f"{where}.field_sources.{field_name}")
            if field_source:
                field_sources[field_name] = field_source
        if None in (first, last, seller, name, distribution_tariffs, cycle, margin, trade_fee, includes_excise, source):
            continue
        offers.append(
            DynamicOffer(
                index=index,
                valid_from=first,
                valid_to=last,
                seller=seller,
                name=name,
                distribution_tariffs=distribution_tariffs,
                billing_cycle_months=cycle,
                margin=margin,
                prosumer_margin=prosumer_margin,
                trade_fee_monthly=trade_fee,
                prosumer_trade_fee_monthly=prosumer_trade_fee,
                market_price_floor=floor,
                market_price_cap=cap,
                includes_excise=includes_excise,
                source=source,
                field_sources=field_sources,
                note=item.get("note"),
            )
        )
    return offers


def _parse_unsupported(reader: _Reader, raw: Any, covers) -> list[UnsupportedEntry]:
    entries = []
    if raw is None:
        return entries
    if not isinstance(raw, list):
        reader.error("unsupported", "oczekiwano listy taryf nieliczonych.")
        return entries
    for index, item in enumerate(raw):
        where = f"unsupported[{index}]"
        if not isinstance(item, dict):
            reader.error(where, "oczekiwano obiektu taryfy.")
            continue
        first, last = reader.period(item, where, covers)
        code = reader.text(item, "code", where)
        name = reader.text(item, "name", where)
        reason = reader.text(item, "reason", where)
        source = reader.source(item.get("source"), f"{where}.source")
        if code and len(code) > 30:
            reader.error(where, "kod taryfy może mieć najwyżej 30 znaków.")
            code = None
        if None in (first, last, code, name, reason, source):
            continue
        entries.append(
            UnsupportedEntry(index=index, code=code, name=name, valid_from=first, valid_to=last, reason=reason, source=source)
        )
    return entries


def _check_operator_consistency(reader: _Reader, data: OperatorFile) -> None:
    """Zgodność wpisów w obrębie pliku, sprawdzana per taryfa."""

    def overlapping(items, label):
        for position, item in enumerate(items):
            for other in items[position + 1:]:
                if _overlap((item[0].valid_from, item[0].valid_to), (other[0].valid_from, other[0].valid_to)):
                    reader.error(label, f"{item[1]} ({_range(item[0])}) nakłada się na {other[1]} ({_range(other[0])}).")

    codes = sorted({code for entry in data.distribution for code in entry.tariffs}
                   | {code for entry in data.energy for code in entry.tariffs}, key=lambda code: code.value)
    for code in codes:
        distribution = [(entry, f"distribution[{entry.index}]") for entry in data.distribution if code in entry.tariffs]
        energy = [(entry, f"energy[{entry.index}]") for entry in data.energy if code in entry.tariffs]
        overlapping(distribution, f"taryfa {code.value}")
        overlapping(energy, f"taryfa {code.value}")
        distribution_days = {day for entry, _ in distribution for day in days_between(entry.valid_from, entry.valid_to)}
        energy_days = {day for entry, _ in energy for day in days_between(entry.valid_from, entry.valid_to)}
        from app.services.tariff_engine import format_day_ranges  # import lokalny: silnik importuje ten moduł

        if distribution_days - energy_days:
            reader.error(
                f"taryfa {code.value}",
                f"są stawki dystrybucji, a brak cen energii dla dni: {format_day_ranges(distribution_days - energy_days)}.",
            )
        if energy_days - distribution_days:
            reader.error(
                f"taryfa {code.value}",
                f"są ceny energii, a brak stawek dystrybucji dla dni: {format_day_ranges(energy_days - distribution_days)}.",
            )
        for distribution_entry, distribution_label in distribution:
            zones = set(distribution_entry.tariffs[code].rates)
            for energy_entry, energy_label in energy:
                if _overlap(
                    (distribution_entry.valid_from, distribution_entry.valid_to),
                    (energy_entry.valid_from, energy_entry.valid_to),
                ) and set(energy_entry.tariffs[code].prices) != zones:
                    reader.error(
                        f"taryfa {code.value}",
                        f"{energy_label} ma ceny dla stref {sorted(energy_entry.tariffs[code].prices)}, a "
                        f"{distribution_label} stawki dla stref {sorted(zones)}.",
                    )

    offers = [(offer, f"dynamic_offers[{offer.index}]") for offer in data.dynamic_offers]
    overlapping(offers, "oferty dynamiczne")
    for offer, label in offers:
        for group in offer.distribution_tariffs:
            covered = {
                day
                for entry in data.distribution
                if group in entry.tariffs
                for day in days_between(entry.valid_from, entry.valid_to)
            }
            missing = [day for day in days_between(offer.valid_from, offer.valid_to) if day not in covered]
            if missing:
                from app.services.tariff_engine import format_day_ranges

                reader.error(
                    label,
                    f"brak stawek dystrybucji {group.value} dla dni: {format_day_ranges(missing)}.",
                )

    by_code: dict[str, list] = {}
    for entry in data.unsupported:
        by_code.setdefault(entry.code.casefold(), []).append((entry, f"unsupported[{entry.index}]"))
    for code, items in by_code.items():
        overlapping(items, f"taryfa nieliczona {items[0][0].code}")


def parse_operator_file(path: Path) -> tuple[OperatorFile | None, list[str]]:
    """Plik operatora → (dane, błędy). Przy błędach dane mogą być niepełne."""
    reader = _Reader(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"{path.name}: nie da się odczytać JSON: {exc}"]
    if not isinstance(raw, dict):
        return None, [f"{path.name}: oczekiwano obiektu JSON."]
    operator_text = reader.text(raw, "operator", "operator")
    operator = None
    if operator_text:
        try:
            operator = DistributionOperatorEnum(operator_text)
        except ValueError:
            reader.error("operator", f"nieznany operator „{operator_text}”.")
    year = raw.get("year")
    if not isinstance(year, int):
        reader.error("year", "„year” musi być liczbą całkowitą.")
    covers = reader.covers(raw)
    reader.documents = reader.documents_section(raw)
    notes = raw.get("notes") or []
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        reader.error("notes", "„notes” musi być listą tekstów.")
        notes = []
    distribution = _parse_distribution(reader, reader.require(raw, "distribution", "distribution"), covers)
    energy = _parse_energy(reader, reader.require(raw, "energy", "energy"), covers)
    dynamic = _parse_dynamic(reader, raw.get("dynamic_offers"), covers)
    unsupported = _parse_unsupported(reader, raw.get("unsupported"), covers)
    if operator is None or not isinstance(year, int) or None in covers:
        return None, reader.errors
    data = OperatorFile(
        path=path,
        operator=operator,
        year=year,
        covers_from=covers[0],
        covers_to=covers[1],
        documents=reader.documents,
        distribution=distribution,
        energy=energy,
        dynamic_offers=dynamic,
        unsupported=unsupported,
        notes=notes,
    )
    _check_operator_consistency(reader, data)
    return data, reader.errors


# ---------------------------------------------------------------- plik regulacyjny


def _parse_bands(reader: _Reader, raw: Any, where: str) -> list[FeeBand]:
    bands = []
    if not isinstance(raw, list) or not raw:
        reader.error(where, "„bands” musi być niepustą listą progów.")
        return bands
    for number, item in enumerate(raw):
        band_where = f"{where}.bands[{number}]"
        if not isinstance(item, dict):
            reader.error(band_where, "oczekiwano obiektu progu.")
            continue
        low = reader.field_decimal(item, "min_kwh", band_where)
        high = item.get("max_kwh")
        high = None if high is None else reader.decimal(high, f"{band_where}, pole „max_kwh”")
        fee = reader.field_decimal(item, "fee", band_where)
        if low is not None and fee is not None:
            bands.append(FeeBand(min_kwh=low, max_kwh=high, fee=fee))
    if bands:
        if bands[0].min_kwh != 0:
            reader.error(where, "pierwszy próg musi zaczynać się od 0 kWh.")
        for previous, current in zip(bands, bands[1:]):
            if previous.max_kwh is None or previous.max_kwh != current.min_kwh:
                reader.error(where, "progi muszą następować po sobie bez przerw (max poprzedniego = min następnego).")
        if bands[-1].max_kwh is not None:
            reader.error(where, "ostatni próg musi mieć \"max_kwh\": null.")
    return bands


def parse_regulatory_file(path: Path) -> tuple[RegulatoryFile | None, list[str]]:
    reader = _Reader(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"{path.name}: nie da się odczytać JSON: {exc}"]
    if not isinstance(raw, dict):
        return None, [f"{path.name}: oczekiwano obiektu JSON."]
    year = raw.get("year")
    if not isinstance(year, int):
        reader.error("year", "„year” musi być liczbą całkowitą.")
    covers = reader.covers(raw)
    reader.documents = reader.documents_section(raw)
    periods = []
    raw_periods = reader.require(raw, "periods", "periods")
    if not isinstance(raw_periods, list) or not raw_periods:
        reader.error("periods", "oczekiwano niepustej listy okresów.")
        raw_periods = []
    for index, item in enumerate(raw_periods):
        where = f"periods[{index}]"
        if not isinstance(item, dict):
            reader.error(where, "oczekiwano obiektu okresu.")
            continue
        first, last = reader.period(item, where, covers)
        values = {}
        for key, label in REGULATORY_VALUES.items():
            entry = reader.require(item, key, where)
            if not isinstance(entry, dict):
                if entry is not None:
                    reader.error(where, f"„{key}” ({label}) musi być obiektem {{\"value\": …, \"source\": …}}.")
                continue
            value = reader.field_decimal(entry, "value", f"{where}.{key}")
            source = reader.source(entry.get("source"), f"{where}.{key}.source")
            if value is not None and source is not None:
                values[key] = (value, source)
        if "vat_rate" in values and values["vat_rate"][0] >= 1:
            reader.error(where, "„vat_rate” podaje się jako ułamek, np. \"0.23\".")
        capacity = reader.require(item, "capacity_fee_monthly", where)
        capacity_bands, capacity_source = [], None
        if isinstance(capacity, dict):
            capacity_bands = _parse_bands(reader, capacity.get("bands"), f"{where}.capacity_fee_monthly")
            capacity_source = reader.source(capacity.get("source"), f"{where}.capacity_fee_monthly.source")
        transition = item.get("transition_fee_monthly")
        transition_bands, transition_source = [], None
        if isinstance(transition, dict):
            transition_bands = _parse_bands(reader, transition.get("bands"), f"{where}.transition_fee_monthly")
            transition_source = reader.source(transition.get("source"), f"{where}.transition_fee_monthly.source")
        elif transition is not None:
            reader.error(where, "„transition_fee_monthly” musi być obiektem z progami albo null (brak opłaty).")
        if first and last and len(values) == len(REGULATORY_VALUES) and capacity_bands and capacity_source:
            periods.append(
                RegulatoryEntry(
                    index=index,
                    valid_from=first,
                    valid_to=last,
                    values=values,
                    capacity_bands=capacity_bands,
                    capacity_source=capacity_source,
                    transition_bands=transition_bands,
                    transition_source=transition_source,
                )
            )
    if not isinstance(year, int) or None in covers:
        return None, reader.errors
    ordered = sorted(periods, key=lambda period: period.valid_from)
    for previous, current in zip(ordered, ordered[1:]):
        if current.valid_from <= previous.valid_to:
            reader.error("periods", f"okres {_range(current)} nakłada się na {_range(previous)}.")
    covered = {day for period in periods for day in days_between(period.valid_from, period.valid_to)}
    missing = [day for day in days_between(*covers) if day not in covered]
    if missing and not reader.errors:
        from app.services.tariff_engine import format_day_ranges

        reader.error("periods", f"brak opłat regulacyjnych dla dni: {format_day_ranges(missing)}.")
    data = RegulatoryFile(
        path=path, year=year, covers_from=covers[0], covers_to=covers[1], documents=reader.documents, periods=periods
    )
    return data, reader.errors


# ---------------------------------------------------------------- zestaw plików


@dataclass
class TariffDataSet:
    operator_files: list[OperatorFile]
    regulatory_files: list[RegulatoryFile]


def find_files(paths: list[Path]) -> list[Path]:
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*.json")))
        else:
            files.append(path)
    return files


def read_data_set(paths: list[Path]) -> TariffDataSet:
    """Wczytuje i waliduje pliki (lub katalogi); rzuca TariffDataError ze wszystkimi błędami."""
    errors: list[str] = []
    operator_files, regulatory_files = [], []
    files = find_files(paths)
    if not files:
        raise TariffDataError(["Nie znaleziono plików JSON z cennikiem."])
    for path in files:
        if path.name == REGULATORY_FILE_NAME:
            data, file_errors = parse_regulatory_file(path)
            if data is not None:
                regulatory_files.append(data)
        else:
            data, file_errors = parse_operator_file(path)
            if data is not None:
                operator_files.append(data)
        errors.extend(file_errors)

    def check_covers(items, label):
        for position, item in enumerate(items):
            for other in items[position + 1:]:
                if _overlap((item.covers_from, item.covers_to), (other.covers_from, other.covers_to)):
                    errors.append(
                        f"{label}: zakresy plików {item.path} i {other.path} nakładają się — "
                        "każdy dzień może pochodzić tylko z jednego pliku."
                    )

    for operator in DistributionOperatorEnum:
        check_covers([item for item in operator_files if item.operator == operator], operator.value)
    check_covers(regulatory_files, "opłaty regulacyjne")
    if errors:
        raise TariffDataError(errors)
    return TariffDataSet(operator_files=operator_files, regulatory_files=regulatory_files)

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.parsers.devices import LOCAL_TIMEZONE
from app.schemas.other import BillingCycleEnum, DistributionOperatorEnum, PhaseTypeEnum, TariffTypeEnum
from app.schemas.user_profile import UserProfile
from app.services.quarter_prices import FeeParameters, KwhPrice, QuarterPrices, TariffRates, decimal, quarter_prices
from app.services.tariff_engine import money
from app.services.tariff_zones import ZoneSchedule, covers

SLOTS_PER_DAY = 96
ZERO = Decimal("0")
DEFAULT_OPERATOR = DistributionOperatorEnum.PGE
DEFAULT_TARIFF = TariffTypeEnum.G11
ZONED_TYPE = "strefowa"
DYNAMIC_TYPE = "dynamiczna"
PART_NAMES = ("energy", "distribution", "fees", "vat")


def polish_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def tariff_key(code: TariffTypeEnum, group: TariffTypeEnum) -> str:
    return f"{group.value}-dynamic" if code == TariffTypeEnum.DYNAMIC else code.value


def tariff_label(code: TariffTypeEnum, group: TariffTypeEnum) -> str:
    return f"{group.value} z ceną dynamiczną" if code == TariffTypeEnum.DYNAMIC else code.value


def price_parts(price: KwhPrice) -> dict[str, Decimal]:
    """Cena 1 kWh w częściach rachunku: energia, dystrybucja, opłaty za kWh (akcyza, jakościowa, OZE,
    kogeneracyjna) netto i VAT; suma części to cena brutto."""
    return {
        "energy": price.energy,
        "distribution": price.network,
        "fees": price.excise + price.quality + price.renewable + price.cogeneration,
        "vat": price.gross - price.net,
    }


def local_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time(), LOCAL_TIMEZONE).astimezone(timezone.utc)


@lru_cache(maxsize=2048)
def _day_moments(day: date) -> tuple[datetime, ...]:
    midnight = datetime.combine(day, time())
    return tuple(midnight + timedelta(minutes=15 * slot) for slot in range(SLOTS_PER_DAY))


@lru_cache(maxsize=2048)
def _clock_shifted(day: date) -> bool:
    midnight = datetime.combine(day, time(), LOCAL_TIMEZONE)
    return midnight.utcoffset() != datetime.combine(day + timedelta(days=1), time(), LOCAL_TIMEZONE).utcoffset()


def _clock_zones(schedule: ZoneSchedule, day: date) -> tuple[int, ...] | list[int]:
    zones = schedule.quarter_zones(day)
    shifted = _clock_shifted(day)
    if not shifted and 0 not in zones:
        return zones
    zones = list(zones)
    for slot, moment in enumerate(_day_moments(day)):
        if shifted:
            clock = moment.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc).astimezone(LOCAL_TIMEZONE)
            if clock.replace(tzinfo=None) != moment:
                zones[slot] = schedule.zone_index(clock.replace(tzinfo=None))
                continue
        if not zones[slot]:
            zones[slot] = schedule.zone_index(moment)
    return zones


class PartsTotal:
    """Koszt brutto w częściach rachunku (zł) dla sumy kWh × cena kwadransu."""

    def __init__(self):
        self.energy = self.distribution = self.fees = self.gross = ZERO

    def add(self, kwh: Decimal, price: KwhPrice) -> None:
        self.energy += kwh * price.energy
        self.distribution += kwh * price.network
        self.fees += kwh * (price.excise + price.quality + price.renewable + price.cogeneration)
        self.gross += kwh * price.gross

    def as_dict(self) -> dict[str, float]:
        vat = self.gross - self.energy - self.distribution - self.fees
        values = {"energy": self.energy, "distribution": self.distribution, "fees": self.fees, "vat": vat}
        return {name: float(money(value)) for name, value in values.items()}


@dataclass(frozen=True)
class PricingProfile:
    """Operator, taryfa i parametry opłat miesięcznych z profilu; bez profilu PGE G11."""

    operator: DistributionOperatorEnum = DEFAULT_OPERATOR
    tariff_type: TariffTypeEnum = DEFAULT_TARIFF
    dynamic: bool = False
    phase_type: PhaseTypeEnum = PhaseTypeEnum.SINGLE_PHASE
    billing_cycle_months: int = BillingCycleEnum.TWO_MONTHS.value
    billing_period_start: date | None = None
    prosumer: bool = False
    from_profile: bool = False

    @property
    def code(self) -> TariffTypeEnum:
        return TariffTypeEnum.DYNAMIC if self.dynamic else self.tariff_type

    @property
    def key(self) -> str:
        return tariff_key(self.code, self.tariff_type)

    @property
    def label(self) -> str:
        return tariff_label(self.code, self.tariff_type)

    @classmethod
    def from_saved(cls, profile: Any) -> PricingProfile:
        if profile is None:
            return cls()
        try:
            data = UserProfile.model_validate(profile)
        except (ValidationError, ValueError):
            return cls()
        base, consumption = data.base_info, data.consumption_and_tariff
        dynamic = consumption.dynamic_price or consumption.tariff_type == TariffTypeEnum.DYNAMIC
        group = DEFAULT_TARIFF if consumption.tariff_type == TariffTypeEnum.DYNAMIC else consumption.tariff_type
        return cls(
            operator=base.distribution_operator,
            tariff_type=group,
            dynamic=dynamic,
            phase_type=base.phase_type,
            billing_cycle_months=base.billing_cycle.value,
            billing_period_start=base.billing_period_start_date,
            prosumer=data.pv_config.mode != "none",
            from_profile=True,
        )


@dataclass(frozen=True)
class TariffOption:
    code: TariffTypeEnum
    group: TariffTypeEnum
    definitions: tuple

    @property
    def dynamic(self) -> bool:
        return self.code == TariffTypeEnum.DYNAMIC

    @property
    def key(self) -> str:
        return tariff_key(self.code, self.group)

    @property
    def label(self) -> str:
        return tariff_label(self.code, self.group)

    @property
    def name(self) -> str | None:
        return next((definition.name for definition in reversed(self.definitions) if definition.name), None)

    def info(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "name": self.name,
            "type": DYNAMIC_TYPE if self.dynamic else ZONED_TYPE,
            "tariff_code": self.code.value,
            "distribution_group": self.group.value,
        }


class TariffCostService:
    """Ceny kwadransów taryf operatora z profilu (wykresy, urządzenia, ceny dynamiczne, optymalizacja), liczone
    przy odczycie z nowego cennika."""

    def __init__(self, tariff_repository, user_repository=None, market_prices=None):
        self.tariff_repository = tariff_repository
        self.user_repository = user_repository
        self.market_prices = market_prices

    def profile(self, user_id) -> PricingProfile:
        if self.user_repository is None or user_id is None:
            return PricingProfile()
        return PricingProfile.from_saved(self.user_repository.get_profile(user_id))

    def options(self, operator: DistributionOperatorEnum, first_day: date, last_day: date) -> list[TariffOption]:
        grouped: dict[tuple[TariffTypeEnum, TariffTypeEnum], list] = {}
        for definition in self.tariff_repository.list_for_period(operator=operator, date_from=first_day, date_to=last_day):
            grouped.setdefault((definition.tariff_code, definition.distribution_group), []).append(definition)
        options = [
            TariffOption(code, group, tuple(sorted(definitions, key=lambda definition: definition.valid_from)))
            for (code, group), definitions in grouped.items()
        ]
        return sorted(options, key=lambda option: (option.dynamic, option.group.value.lower()))

    @staticmethod
    def select(profile: PricingProfile, options: list[TariffOption]) -> tuple[TariffOption | None, str | None]:
        """Taryfa kosztów: z profilu, a gdy operator nie ma jej stawek w tym okresie, G11 tego operatora."""
        by_key = {option.key: option for option in options}
        if profile.key in by_key:
            return by_key[profile.key], None
        operator = profile.operator.value
        fallback = by_key.get(DEFAULT_TARIFF.value) or (options[0] if options else None)
        if fallback is None:
            return None, f"Operator {operator} nie ma w cenniku stawek dla tego okresu, więc nie liczymy kosztów."
        return fallback, (
            f"Operator {operator} nie ma w cenniku stawek taryfy {profile.label} dla tego okresu, "
            f"więc koszty liczymy dla taryfy {fallback.label}."
        )

    def dynamic_offer(
        self, profile: PricingProfile, first_day: date, last_day: date
    ) -> tuple[TariffOption | None, str | None]:
        """Oferta z ceną dynamiczną operatora z profilu z grupą dystrybucyjną z profilu (albo G11)."""
        offers = [option for option in self.options(profile.operator, first_day, last_day) if option.dynamic]
        by_group = {option.group: option for option in offers}
        operator = profile.operator.value
        if profile.tariff_type in by_group:
            return by_group[profile.tariff_type], None
        fallback = by_group.get(DEFAULT_TARIFF) or (offers[0] if offers else None)
        if fallback is None:
            return None, f"Operator {operator} nie ma w cenniku oferty z ceną dynamiczną dla tego okresu."
        return fallback, (
            f"Operator {operator} nie ma oferty z ceną dynamiczną z dystrybucją {profile.tariff_type.value}, "
            f"więc pokazujemy ofertę z dystrybucją {fallback.group.value}."
        )

    def prices(
        self,
        option: TariffOption,
        start_utc: datetime,
        end_utc: datetime,
        profile: PricingProfile,
        periods=None,
        fee_parameters: FeeParameters | None = None,
        market_price=None,
    ) -> QuarterPrices:
        if periods is None:
            periods = self.tariff_repository.list_regulatory_periods(
                date_from=start_utc.astimezone(LOCAL_TIMEZONE).date(),
                date_to=(end_utc - timedelta(minutes=15)).astimezone(LOCAL_TIMEZONE).date(),
            )
        if option.dynamic and market_price is None and self.market_prices is not None:
            self.market_prices.preload_rce(start_utc, end_utc)
            market_price = self.market_prices.rce
        return quarter_prices(
            option.definitions, periods, start_utc, end_utc,
            market_price=market_price, prosumer=profile.prosumer, fee_parameters=fee_parameters,
        )

    def chart_prices(
        self, profile: PricingProfile, usage: dict[str, list[float | None]], keys=None
    ) -> dict[str, dict]:
        keys = None if keys is None else set(keys)
        data_start = self.tariff_repository.first_valid_from(operator=profile.operator)
        days = sorted(
            date.fromisoformat(day) for day, slots in usage.items()
            if any(kwh is not None for kwh in slots) and (data_start is None or day >= data_start.isoformat())
        )
        if not days or keys == set():
            return {}
        periods = self.tariff_repository.list_regulatory_periods(date_from=days[0], date_to=days[-1])
        options = [option for option in self.options(profile.operator, days[0], days[-1]) if keys is None or option.key in keys]
        market = None
        if any(option.dynamic for option in options) and self.market_prices is not None:
            market = self._market_by_day(days)
        slot_prices = {}
        for option in options:
            if option.dynamic and market is None:
                continue
            try:
                prices_by_day = self._chart_days(option, days, periods, profile.prosumer, market)
            except (ValueError, LookupError):
                continue
            slot_prices[option.key] = {"type": DYNAMIC_TYPE if option.dynamic else ZONED_TYPE, "prices_by_day": prices_by_day}
        return slot_prices

    def _market_by_day(self, days: list[date]) -> dict[date, list[float | None]]:
        self.market_prices.preload_rce(local_midnight_utc(days[0]), local_midnight_utc(days[-1] + timedelta(days=1)))
        rce = self.market_prices.rce
        market = {}
        for day in days:
            row = []
            for moment in _day_moments(day):
                try:
                    row.append(rce(moment))
                except ValueError:
                    row.append(None)
            market[day] = row
        return market

    @staticmethod
    def _chart_days(option: TariffOption, days, periods, prosumer: bool, market) -> dict[str, list[float | None]]:
        schedule = ZoneSchedule(option.definitions)
        rates: dict[tuple[int, int], tuple[TariffRates, Decimal, dict[int, Any]]] = {}
        prices_by_day = {}
        for day in days:
            definition = schedule.definition_for(day)
            period = next((item for item in periods if covers(item, day)), None)
            if definition is None or period is None:
                prices_by_day[day.isoformat()] = [None] * SLOTS_PER_DAY
                continue
            key = (id(definition), id(period))
            if key not in rates:
                rates[key] = (TariffRates(definition, period), Decimal(1) + decimal(period.vat_rate), {})
            tariff_rates, vat_factor, by_zone = rates[key]
            zones = _clock_zones(schedule, day)
            if not tariff_rates.dynamic:
                for zone in set(zones) - by_zone.keys():
                    by_zone[zone] = round(float(tariff_rates.price(zone).gross), 5)
                prices_by_day[day.isoformat()] = [by_zone[zone] for zone in zones]
                continue
            # Cena kwadransa jak w quarter_prices: (cena giełdowa w granicach oferty + stała część strefy) × VAT,
            # liczona na float, bo to tylko wykres (zaokrąglony do 5 miejsc).
            for zone in set(zones) - by_zone.keys():
                by_zone[zone] = float(
                    tariff_rates.price(zone, Decimal(0), prosumer).net - tariff_rates.market_part(Decimal(0))
                )
            floor, cap = (None if limit is None else float(limit) / 1000 for limit in tariff_rates.market_limits)
            vat = float(vat_factor)
            prices_by_day[day.isoformat()] = [
                None if price is None
                else round((min(max(price, floor if floor is not None else price), cap if cap is not None else price)
                            + by_zone[zone]) * vat, 5)
                for zone, price in zip(zones, market[day])
            ]
        return prices_by_day

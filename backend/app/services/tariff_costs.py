from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from dateutil.relativedelta import relativedelta
from pydantic import ValidationError

from app.parsers.devices import LOCAL_TIMEZONE
from app.schemas.other import BillingCycleEnum, DistributionOperatorEnum, PhaseTypeEnum, TariffTypeEnum
from app.schemas.user_profile import UserProfile
from app.services.quarter_prices import FeeParameters, KwhPrice, MonthlyFeesPeriod, QuarterPrices, quarter_prices
from app.services.tariff_engine import DAYS_IN_YEAR, billing_cycle_months, money

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


def local_slot(moment: datetime) -> tuple[str, int]:
    local = moment.astimezone(LOCAL_TIMEZONE)
    return local.date().isoformat(), local.hour * 4 + local.minute // 15


def cycle_start(day: date, billing_start: date, months: int) -> date:
    months_since_start = (day.year - billing_start.year) * 12 + day.month - billing_start.month
    candidate = billing_start + relativedelta(months=(months_since_start // months) * months)
    if candidate > day:
        candidate -= relativedelta(months=months)
    return candidate


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


@dataclass(frozen=True)
class UsageCosts:
    slot_prices: dict[str, dict]
    tariffs: dict[str, dict]
    pricing: dict[str, Any]


class TariffCostService:
    """Ceny kwadransów i koszty zużycia we wszystkich taryfach operatora z profilu, liczone przy odczycie
    z nowego cennika, więc zmiana profilu albo cennika od razu zmienia koszty także starszych plików."""

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

    def usage_costs(
        self, profile: PricingProfile, usage: dict[str, list[float | None]], all_tariffs: bool = True
    ) -> UsageCosts:
        """Ceny kwadransów (do wykresów) i rachunek każdej taryfy dla serii {dzień: [96 kWh | None]}.

        Rachunek liczymy jak Wyniki kalkulacji: w każdym cyklu rozliczeniowym energia z cen kwadransów
        plus opłaty miesięczne za dni okresu, zaokrąglone do grosza."""
        days = sorted(day for day, slots in usage.items() if any(kwh is not None for kwh in slots))
        if not days:
            return UsageCosts({}, {}, self._pricing(profile, None, None, all_tariffs))
        first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        notes = []
        data_start = self.tariff_repository.first_valid_from(operator=profile.operator)
        if data_start is not None and first < data_start:
            operator = profile.operator.value
            if last < data_start:
                note = (
                    f"Koszty u operatora {operator} liczymy od {polish_date(data_start)}, a wybrany okres obejmuje "
                    f"tylko wcześniejsze dni ({polish_date(first)} – {polish_date(last)})."
                )
                return UsageCosts({}, {}, self._pricing(profile, None, note, all_tariffs))
            notes.append(
                f"Okres zaczyna się {polish_date(first)}, a stawki taryfowe mamy od {polish_date(data_start)}. "
                f"Dni przed {polish_date(data_start)} nie liczymy — koszty obejmują "
                f"{polish_date(data_start)} – {polish_date(last)}."
            )
            days = [day for day in days if day >= data_start.isoformat()]
            usage = {day: slots for day, slots in usage.items() if day >= data_start.isoformat()}
            first = data_start
        start, end = local_midnight_utc(first), local_midnight_utc(last + timedelta(days=1))
        options = self.options(profile.operator, first, last)
        periods = self.tariff_repository.list_regulatory_periods(date_from=first, date_to=last)
        total_kwh = sum(kwh for slots in usage.values() for kwh in slots if kwh)
        annual_kwh = Decimal(str(round(total_kwh * DAYS_IN_YEAR / ((last - first).days + 1), 3)))
        selected, selection_note = self.select(profile, options)
        notes.append(selection_note)
        if not all_tariffs:
            options = [selected] if selected else []

        slot_prices, tariffs, slot_keys = {}, {}, {}
        for option in options:
            entry = {
                **option.info(),
                "is_profile": profile.from_profile and option.key == profile.key,
                "total_usage_kwh": round(total_kwh, 2),
            }
            available_from = option.definitions[0].valid_from
            if available_from > first:
                tariffs[option.key] = {
                    **entry,
                    "estimated_cost_pln": None,
                    "note": f"{option.name or option.label}: oferta dostępna od {polish_date(available_from)}, "
                    f"a okres zaczyna się {polish_date(first)}.",
                }
                continue
            try:
                months = billing_cycle_months(option.definitions, profile.billing_cycle_months)
                fees = FeeParameters(profile.phase_type, months, annual_kwh, profile.prosumer)
                quarters = self.prices(option, start, end, profile, periods, fees)
            except (ValueError, LookupError) as exc:
                tariffs[option.key] = {**entry, "estimated_cost_pln": None, "note": str(exc)}
                continue
            by_slot = self.by_local_slot(quarters, days, slot_keys)
            slot_prices[option.key] = {
                "type": entry["type"],
                "prices_by_day": {
                    day: [self._rounded(by_slot.get((day, slot))) for slot in range(SLOTS_PER_DAY)]
                    for day in days
                },
            }
            tariffs[option.key] = {
                **entry,
                "billing_cycle_months": months,
                **self._bill(profile, months, usage, by_slot, quarters.monthly_fees, first, last),
            }
        note = " ".join(item for item in notes if item) or None
        return UsageCosts(slot_prices, tariffs, self._pricing(profile, selected, note, all_tariffs))

    @staticmethod
    def by_local_slot(quarters: QuarterPrices, days=(), keys=None) -> dict[tuple[str, int], KwhPrice]:
        """Ceny według dnia lokalnego i numeru kwadransa doby, jak w seriach zużycia; powtórzoną godzinę
        przy zmianie czasu przypisujemy do pierwszego wystąpienia. Kwadrans, którego nie ma w dniu zmiany
        czasu na letni, dostaje cenę chwili, którą wskazuje ten czas lokalny (tak jak w Wynikach kalkulacji)."""
        by_slot = {}
        keys = {} if keys is None else keys
        for moment, price in quarters.prices.items():
            key = keys.get(moment)
            if key is None:
                key = keys[moment] = local_slot(moment)
            by_slot.setdefault(key, price)
        priced = Counter(day for day, _ in by_slot)
        for day in days:
            if priced[day] >= SLOTS_PER_DAY:
                continue
            for slot in range(SLOTS_PER_DAY):
                if (day, slot) in by_slot:
                    continue
                naive = datetime.combine(date.fromisoformat(day), time(slot // 4, slot % 4 * 15))
                price = quarters.prices.get(naive.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc))
                if price is not None:
                    by_slot[(day, slot)] = price
        return by_slot

    @staticmethod
    def _rounded(price: KwhPrice | None) -> float | None:
        return None if price is None else round(float(price.gross), 5)

    @staticmethod
    def _pricing(
        profile: PricingProfile, selected: TariffOption | None, note: str | None, all_tariffs: bool = True
    ) -> dict[str, Any]:
        return {
            "operator": profile.operator.value,
            "from_profile": profile.from_profile,
            "profile_tariff": profile.key,
            "tariff_key": selected.key if selected else None,
            "tariff_label": selected.label if selected else None,
            "note": note,
            "all_tariffs": all_tariffs,
        }

    @staticmethod
    def _bill(
        profile: PricingProfile,
        months: int,
        usage: dict[str, list[float | None]],
        by_slot: dict[tuple[str, int], KwhPrice],
        fee_periods: tuple[MonthlyFeesPeriod, ...],
        first: date,
        last: date,
    ) -> dict[str, Any]:
        billing_start = profile.billing_period_start or first.replace(day=1)
        cycles: dict[date, list[Decimal]] = {}
        parts = PartsTotal()
        slots_used = slots_missing = 0
        for day, slots in usage.items():
            if not any(kwh is not None for kwh in slots):
                continue
            cycle = cycles.setdefault(cycle_start(date.fromisoformat(day), billing_start, months), [ZERO, ZERO, ZERO])
            for slot, kwh in enumerate(slots):
                if not kwh or kwh <= 0:
                    continue
                amount = Decimal(str(kwh))
                cycle[1] += amount
                slots_used += 1
                price = by_slot.get((day, slot))
                if price is None:
                    slots_missing += 1
                    continue
                cycle[0] += amount * price.gross
                cycle[2] += amount
                parts.add(amount, price)

        total = energy_total = ZERO
        unknown = False
        for start_day, (energy, kwh, covered) in sorted(cycles.items()):
            if covered < kwh:
                if covered == 0:
                    unknown = True
                    continue
                energy = energy * kwh / covered
            cycle_end = start_day + relativedelta(months=months) - timedelta(days=1)
            first_billed, last_billed = max(start_day, first), min(cycle_end, last)
            days_in_cycle = Decimal((cycle_end - start_day).days + 1)
            fees = sum(
                (
                    period.fees.gross * months * Decimal((min(period.valid_to, last_billed) - max(period.valid_from, first_billed)).days + 1)
                    / days_in_cycle
                    for period in fee_periods
                    if max(period.valid_from, first_billed) <= min(period.valid_to, last_billed)
                ),
                ZERO,
            )
            total += money(energy + fees)
            energy_total += energy

        estimated = None if unknown else money(total)
        energy_cost = None if unknown else money(energy_total)
        return {
            "estimated_cost_pln": None if estimated is None else float(estimated),
            "energy_cost_pln": None if energy_cost is None else float(energy_cost),
            "monthly_fees_pln": None if estimated is None else float(estimated - energy_cost),
            "monthly_fee_gross": float(money(fee_periods[-1].fees.gross)) if fee_periods else None,
            "cost_breakdown": parts.as_dict(),
            "price_coverage": round((slots_used - slots_missing) / slots_used, 4) if slots_used else 1.0,
            "missing_price_intervals": slots_missing,
        }

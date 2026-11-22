from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import logging
from typing import Any, NamedTuple
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from dateutil.relativedelta import relativedelta

from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.repositories.tariff_definition_repository import TariffDefinitionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.calculation import (
    AnnualConsumption, CalculationDetails, PVDetails, TariffChoice, TariffData, UnsupportedTariffInfo,
)
from app.schemas.other import (
    BillingCycleEnum, DistributionOperatorEnum, PhaseTypeEnum, PVTypeEnum, TariffTypeEnum, TypeOfMarketEnergyEnum,
)
from app.schemas.user_profile import PVConfig, UserProfile
from app.services.pv_service import DynamicMarketPriceResolver, PVBalancingEngine
from app.services.tariff_engine import (
    DAYS_IN_YEAR,
    BillingContext,
    FinancialSettlement,
    ZonedTariffCalculationStrategy,
    billing_cycle_months,
    covers,
    days_between,
    format_day_ranges,
)
from app.services.tariff_costs import tariff_label
from app.services.tariff_zones import ZoneSchedule


logger = logging.getLogger(__name__)
PV_CONFIG = TypeAdapter(PVConfig)


DEFAULT_CONTRACTED_POWER_KW = 7.0
TariffKey = tuple[TariffTypeEnum, TariffTypeEnum]


def _polish_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def key_order(key: TariffKey) -> tuple[bool, str]:
    return key[0] == TariffTypeEnum.DYNAMIC, key[1].value.lower()


def profile_key(tariff_data: TariffData) -> TariffKey:
    if tariff_data.dynamic_price:
        return TariffTypeEnum.DYNAMIC, tariff_data.tariff_type
    return tariff_data.tariff_type, tariff_data.tariff_type


def result_for(details: CalculationDetails, key: TariffKey) -> dict | None:
    code, group = key
    if code == TariffTypeEnum.DYNAMIC:
        return (details.dynamic_calculations or {}).get(group.value)
    return (details.tariff_calculations or {}).get(code.value)


class ProfileInputs(NamedTuple):
    pv_config: Any
    tariff_data: TariffData
    from_profile: bool


@dataclass
class TariffRun:
    details: CalculationDetails
    inputs: ProfileInputs
    definitions: dict[TariffKey, list]
    regulatory_periods: list
    profile_key: TariffKey
    selected_key: TariffKey
    selection_note: str | None
    first_day: date
    last_day: date


class CalculationsService:
    def __init__(
        self,
        user_repository: UserRepository,
        energy_file_repository: EnergyDataFileRepository,
        energy_reading_repository: EnergyReadingRepository,
        tariff_repository: TariffDefinitionRepository,
        market_price_repository=None,
        pv_balancer: PVBalancingEngine | None = None,
        tariff_engine: ZonedTariffCalculationStrategy | None = None,
        settlement: FinancialSettlement | None = None,
        market_prices: DynamicMarketPriceResolver | None = None,
    ):
        self.user_repository = user_repository
        self.energy_file_repository = energy_file_repository
        self.energy_reading_repository = energy_reading_repository
        self.tariff_repository = tariff_repository
        if market_prices is None and market_price_repository is not None:
            market_prices = DynamicMarketPriceResolver(market_price_repository)
        self.market_prices = market_prices
        self.pv_balancer = pv_balancer or PVBalancingEngine(market_prices)
        self.tariff_engine = tariff_engine or ZonedTariffCalculationStrategy()
        if market_prices is not None:
            # Ceny RCE z tej samej pamięci podręcznej co net-billing (wczytywane miesiącami, nie kwadransami).
            self.tariff_engine.set_dynamic_price_resolver(
                lambda timestamp: market_prices(timestamp, TypeOfMarketEnergyEnum.RCE)
            )
        self.settlement = settlement or FinancialSettlement()

    def _load_inputs(self, user_id: UUID, file_id: UUID, readings=None, tariff: TariffChoice | None = None):
        """`tariff`: grupa i umowa dynamiczna zamiast tych z profilu (optymalizacja z wyborem taryfy)."""
        profile = self.user_repository.get_profile(user_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profil użytkownika nie został znaleziony.")

        energy_file = self.energy_file_repository.get_by_id_for_user(file_id, user_id)
        if energy_file is None:
            raise HTTPException(status_code=404, detail="Plik danych energii nie został znaleziony.")

        if energy_file.status != energy_file.STATUS_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail=f"Dane pliku nie są dostępne (status: {energy_file.status}).",
            )

        inputs = self._inputs_from_profile(profile, tariff)
        if readings is None:
            readings = self.energy_reading_repository.list_for_file(file_id)
        if not readings:
            raise HTTPException(status_code=409, detail="Brak surowych odczytów energii dla pliku.")
        return inputs, readings

    @staticmethod
    def _inputs_from_profile(profile, tariff: TariffChoice | None) -> "ProfileInputs":
        try:
            profile_data = UserProfile.model_validate(profile)
        except ValidationError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Profil użytkownika jest niekompletny lub nieaktualny. "
                    "Uzupełnij i zapisz profil przed uruchomieniem kalkulacji."
                ),
            ) from exc
        base_info = profile_data.base_info
        tariff_type, dynamic_price = (tariff or TariffChoice()).resolve(profile_data)
        tariff_data = TariffData(
            tariff_type=tariff_type,
            dynamic_price=dynamic_price,
            billing_cycle=base_info.billing_cycle,
            billing_period_start_date=base_info.billing_period_start_date,
            distribution_operator=base_info.distribution_operator,
            phase_type=base_info.phase_type,
            contracted_power_kw=base_info.contracted_power_kw,
        )
        return ProfileInputs(profile_data.pv_config, tariff_data, from_profile=True)

    def _details(self, pv_config, tariff_data, readings, first_day, warnings) -> CalculationDetails:
        if first_day is not None:
            readings = [reading for reading in readings if reading.measured_at.date() >= first_day]
        used_energy_cycles, produced_energy_cycles = self._cycles_from_readings(readings, tariff_data)

        pv_details = self._build_pv_details(pv_config, produced_energy_cycles)
        warnings = list(warnings or [])
        exported_kwh = sum(kwh for _, records in produced_energy_cycles for _, kwh in records)
        if pv_details is None and exported_kwh > 0:
            exported_text = f"{exported_kwh:.2f}".replace(".", ",")
            warnings.append(
                f"Plik zawiera {exported_text} kWh energii oddanej do sieci, ale profil nie ma "
                "instalacji PV. Kalkulacja pomija oddanie energii; uzupełnij instalację PV w profilu, "
                "żeby rozliczyć ją w net-meteringu albo net-billingu."
            )

        return CalculationDetails(
            pv_details=pv_details,
            used_energy_cycles=used_energy_cycles,
            tariff_data=tariff_data,
            annual_consumption=self._annual_consumption(readings),
            warnings=warnings or None,
        )

    def profile_inputs(self, user_id: UUID, first_day: date) -> ProfileInputs:
        profile = self.user_repository.get_profile(user_id)
        if profile is None:
            return self.default_inputs(first_day)
        try:
            return self._inputs_from_profile(profile, None)
        except HTTPException:
            return self.default_inputs(first_day)

    @staticmethod
    def default_inputs(first_day: date) -> ProfileInputs:
        return ProfileInputs(
            {"mode": "none"},
            TariffData(
                tariff_type=TariffTypeEnum.G11,
                billing_cycle=BillingCycleEnum.TWO_MONTHS,
                billing_period_start_date=first_day.replace(day=1),
                distribution_operator=DistributionOperatorEnum.PGE,
                phase_type=PhaseTypeEnum.SINGLE_PHASE,
                contracted_power_kw=DEFAULT_CONTRACTED_POWER_KW,
            ),
            from_profile=False,
        )

    def perform_tariff_calculations(
        self, user_id: UUID, file_id: UUID, readings=None, selected_only: bool = False,
        tariff: TariffChoice | None = None,
    ) -> CalculationDetails:
        """Rachunki dla pliku; `readings` zastępuje odczyty z bazy (np. zużycie po przesunięciu akcji),
        `selected_only` liczy tylko wybraną taryfę (grupa albo grupa z ceną dynamiczną): z profilu albo
        z `tariff` (wybór z ekranu optymalizacji)."""
        inputs, readings = self._load_inputs(user_id, file_id, readings, tariff)
        return self.calculate(readings, inputs, selected_only=selected_only, user_id=user_id).details

    def calculate(
        self, readings, inputs: ProfileInputs, *, selected_only: bool = False, fallback: bool = False,
        user_id: UUID | None = None,
    ) -> TariffRun:
        if not readings:
            raise HTTPException(status_code=409, detail="Brak odczytów energii w wybranym okresie.")
        tariff_data = inputs.tariff_data
        operator = tariff_data.distribution_operator
        file_first = min(reading.measured_at for reading in readings).date()
        file_last = max(reading.measured_at for reading in readings).date()

        # Wcześniejsze dni pliku nie mają stawek w bazie: liczymy od pierwszego dnia z cennikiem operatora.
        warnings = []
        data_start = self.tariff_repository.first_valid_from(operator=operator)
        first_day = file_first
        if data_start is not None and file_first < data_start:
            if file_last < data_start:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Rachunki u operatora {operator.value} liczymy od {_polish_date(data_start)}, a plik obejmuje "
                        f"tylko wcześniejsze dni ({_polish_date(file_first)} – {_polish_date(file_last)})."
                    ),
                )
            first_day = data_start
            warnings.append(
                f"Plik zaczyna się {_polish_date(file_first)}, a stawki taryfowe mamy od {_polish_date(data_start)}. "
                f"Dni przed {_polish_date(data_start)} nie liczymy — rachunek obejmuje {_polish_date(data_start)} – "
                f"{_polish_date(file_last)}."
            )

        definitions = self.tariff_repository.list_for_period(operator=operator, date_from=first_day, date_to=file_last)
        if not definitions:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Brak stawek taryfowych operatora {operator.value} dla okresu pliku "
                    f"{first_day.isoformat()} – {file_last.isoformat()}."
                ),
            )
        regulatory_periods = self.tariff_repository.list_regulatory_periods(date_from=first_day, date_to=file_last)
        missing_days = [
            day for day in days_between(first_day, file_last)
            if not any(covers(period, day) for period in regulatory_periods)
        ]
        if missing_days:
            # Bez opłat regulacyjnych rachunek byłby zaniżony, więc nie liczymy go wcale.
            raise HTTPException(
                status_code=409,
                detail=(
                    "Brak opłat regulacyjnych (jakościowej, OZE, kogeneracyjnej, mocowej i przejściowej) "
                    f"dla dni: {format_day_ranges(missing_days)}."
                ),
            )

        profile_months = tariff_data.billing_cycle.value
        offered_cycles = sorted(
            {
                fee.billing_cycle_months
                for definition in definitions
                if definition.tariff_code != TariffTypeEnum.DYNAMIC
                for fee in definition.subscription_fees
            }
        )
        if offered_cycles and profile_months not in offered_cycles:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Operator {operator.value} nie oferuje w grupach G okresu rozliczeniowego {profile_months} mies. "
                    f"(dostępne: {', '.join(str(months) for months in offered_cycles)} mies.). Zmień okres w profilu."
                ),
            )

        # Taryfy strefowe po kodzie; oferta dynamiczna osobno dla każdej grupy dystrybucyjnej.
        definitions_by_key: dict[tuple[TariffTypeEnum, TariffTypeEnum], list] = {}
        for definition in definitions:
            key = (definition.tariff_code, definition.distribution_group)
            definitions_by_key.setdefault(key, []).append(definition)
        for tariff_definitions in definitions_by_key.values():
            tariff_definitions.sort(key=lambda item: item.valid_from)
        requested_key = profile_key(tariff_data)
        selected_key, selection_note = requested_key, None
        if fallback and requested_key not in definitions_by_key:
            selected_key = next(
                (key for key in ((TariffTypeEnum.G11, TariffTypeEnum.G11), *sorted(definitions_by_key, key=key_order))
                 if key in definitions_by_key),
            )
            selection_note = (
                f"Operator {operator.value} nie ma w cenniku stawek taryfy {tariff_label(*requested_key)} dla tego okresu, "
                f"więc liczymy taryfę {tariff_label(*selected_key)}."
            )

        base_details = self._details(inputs.pv_config, tariff_data, readings, first_day, warnings)
        # Ceny RCE są potrzebne do ofert dynamicznych, które liczymy, i do wyceny oddania w net-billingu.
        dynamic_needed = (
            selected_key[0] == TariffTypeEnum.DYNAMIC if selected_only
            else any(definition.tariff_code == TariffTypeEnum.DYNAMIC for definition in definitions)
        )
        net_billing = base_details.pv_details is not None and base_details.pv_details.mode == PVTypeEnum.NET_BILLING
        needs_market_prices = dynamic_needed or net_billing
        if needs_market_prices and self.market_prices is not None:
            # Ceny RCE całego okresu jednym zapytaniem zamiast osobnego dla każdego miesiąca.
            self.market_prices.preload_rce(
                datetime.combine(first_day, time(), LOCAL_TIMEZONE).astimezone(timezone.utc),
                datetime.combine(file_last + timedelta(days=1), time(), LOCAL_TIMEZONE).astimezone(timezone.utc),
            )
        consumption = base_details.annual_consumption
        context = BillingContext(
            regulatory_periods=regulatory_periods,
            annual_kwh=Decimal(str(consumption.annual_kwh)),
            first_day=first_day,
            last_day=file_last,
            raw_cycles=base_details.used_energy_cycles,
            prosumer=base_details.pv_details is not None,
        )

        calculations = {}
        dynamic_calculations = {}
        calculation_errors = {}
        tariff_notes = {}
        cycle_details_by_months: dict[int, CalculationDetails] = {}
        for (tariff_code, group), tariff_definitions in definitions_by_key.items():
            if selected_only and (tariff_code, group) != selected_key:
                continue
            dynamic = tariff_code == TariffTypeEnum.DYNAMIC
            tariff_name = f"dynamic {group.value}" if dynamic else tariff_code.value
            note_key = tariff_code.value
            available_from = tariff_definitions[0].valid_from
            if available_from > first_day:
                name = next((definition.name for definition in tariff_definitions if definition.name), tariff_name)
                tariff_notes[note_key] = (
                    f"{name}: oferta dostępna od {_polish_date(available_from)}, a plik zaczyna się "
                    f"{_polish_date(first_day)}."
                )
                continue
            pv_mode = base_details.pv_details.mode if base_details.pv_details is not None else None
            if dynamic and pv_mode == PVTypeEnum.NET_METERING:
                tariff_notes[note_key] = (
                    "Oferty z ceną dynamiczną nie liczymy przy net-meteringu: system opustów bilansuje energię "
                    "w strefach, a cena dynamiczna wymaga zużycia w kwadransach."
                )
                continue
            try:
                # Płytka kopia: odczyty i cykle są tylko czytane, każda taryfa zmienia jedynie własne tariff_data
                # i podmienia (a nie modyfikuje) listy cykli.
                details = base_details.model_copy()
                details.tariff_data = base_details.tariff_data.model_copy(update={"tariff_type": tariff_code})
                months = billing_cycle_months(tariff_definitions, profile_months)
                if months != profile_months:
                    # Oferta wymaga własnego okresu (np. 1 miesiąc) niezależnie od okresu z profilu.
                    details.tariff_data.billing_cycle = BillingCycleEnum(months)
                    if months not in cycle_details_by_months:
                        cycle_details_by_months[months] = self._details(
                            inputs.pv_config, details.tariff_data, readings, first_day, warnings
                        )
                    cycle_details = cycle_details_by_months[months]
                    details.used_energy_cycles = cycle_details.used_energy_cycles
                    details.pv_details = cycle_details.pv_details
                    tariff_context = BillingContext(
                        regulatory_periods=context.regulatory_periods,
                        annual_kwh=context.annual_kwh,
                        first_day=context.first_day,
                        last_day=context.last_day,
                        raw_cycles=cycle_details.used_energy_cycles,
                        prosumer=context.prosumer,
                    )
                else:
                    tariff_context = context
                schedule = ZoneSchedule(tariff_definitions)
                if details.pv_details is not None:
                    details = self.pv_balancer.balance_pv(details, schedule)
                result = self.tariff_engine.calculate(details, tariff_definitions, tariff_context, schedule)
                result = self.settlement.settle(result, details.overpayment_cycles)
                (dynamic_calculations if dynamic else calculations)[group.value if dynamic else tariff_name] = (
                    result.as_dict()
                )
            except (ValueError, KeyError) as exc:
                calculation_errors[tariff_name] = str(exc)
                logger.warning("Skipping tariff %s for user %s: %s", tariff_name, user_id, exc)

        if not calculations and not dynamic_calculations:
            # Powody pominięcia (np. cena dynamiczna przy net-meteringu) idą do komunikatu, inaczej zostaje sam ogólnik.
            reasons = [f"{name}: {error}" for name, error in calculation_errors.items()] + list(tariff_notes.values())
            raise HTTPException(
                status_code=409,
                detail=" ".join(["Brak kompletnych danych taryfowych dla tego pliku.", *reasons]),
            )
        base_details.tariff_calculations = calculations
        base_details.dynamic_calculations = dynamic_calculations or None
        base_details.tariff_calculation_errors = calculation_errors or None
        base_details.tariff_calculation = result_for(base_details, selected_key)
        base_details.tariff_notes = tariff_notes or None
        base_details.unsupported_tariffs = [
            UnsupportedTariffInfo(code=item.tariff_code, name=item.name, reason=item.reason)
            for item in self._unique_unsupported(
                self.tariff_repository.list_unsupported(operator=operator, date_from=first_day, date_to=file_last)
            )
        ] or None
        return TariffRun(
            details=base_details,
            inputs=inputs,
            definitions=definitions_by_key,
            regulatory_periods=regulatory_periods,
            profile_key=requested_key,
            selected_key=selected_key,
            selection_note=selection_note,
            first_day=first_day,
            last_day=file_last,
        )

    @staticmethod
    def _unique_unsupported(items):
        seen = {}
        for item in items:
            seen.setdefault(item.tariff_code.casefold(), item)
        return list(seen.values())

    @staticmethod
    def _cycles_from_readings(readings, tariff_data: TariffData):
        if not readings:
            raise HTTPException(status_code=409, detail="Brak surowych odczytów energii dla pliku.")

        used_cycles = {}
        produced_cycles = {}
        cycle_starts = set()
        starts_by_day: dict[date, datetime] = {}
        for reading in readings:
            timestamp = reading.measured_at
            used = float(reading.energy_kwh)
            produced = float(reading.exported_kwh)
            day = timestamp.date()
            cycle_start = starts_by_day.get(day)
            if cycle_start is None:
                cycle_start = starts_by_day[day] = CalculationsService._cycle_start(
                    day,
                    tariff_data.billing_period_start_date,
                    tariff_data.billing_cycle.value,
                )
            cycle_starts.add(cycle_start)
            if used > 0:
                used_cycles.setdefault(cycle_start, []).append((timestamp, used))
            if produced > 0:
                produced_cycles.setdefault(cycle_start, []).append((timestamp, produced))

        return (
            [
                (cycle_start, used_cycles.get(cycle_start, []))
                for cycle_start in sorted(cycle_starts)
            ],
            [
                (cycle_start, produced_cycles.get(cycle_start, []))
                for cycle_start in sorted(cycle_starts)
            ],
        )

    @staticmethod
    def _annual_consumption(readings) -> AnnualConsumption:
        """Pobór z sieci w rozliczanych dniach pliku przeskalowany do roku (próg opłaty mocowej i przejściowej)."""
        if not readings:
            raise HTTPException(status_code=409, detail="Brak surowych odczytów energii dla pliku.")
        first_day = min(reading.measured_at for reading in readings).date()
        last_day = max(reading.measured_at for reading in readings).date()
        days = (last_day - first_day).days + 1
        consumption_kwh = sum(float(reading.energy_kwh) for reading in readings)
        return AnnualConsumption(
            data_start=first_day,
            data_end=last_day,
            days=days,
            consumption_kwh=round(consumption_kwh, 3),
            annual_kwh=round(consumption_kwh * DAYS_IN_YEAR / days, 3),
            scaled=days != DAYS_IN_YEAR,
        )

    @staticmethod
    def _build_pv_details(pv_config, produced_energy_cycles):
        if isinstance(pv_config, dict):
            pv_config = PV_CONFIG.validate_python(pv_config)
        if pv_config.mode == "none":
            return None

        details = {
            "pv_energy_cycles": produced_energy_cycles,
            "mode": pv_config.mode,
        }
        if pv_config.mode == "net_metering":
            details["power_of_pv_kwp"] = pv_config.power_of_pv_kwp
        else:
            details["type_of_market_energy"] = pv_config.type_of_price
        return PVDetails.model_validate(details)


    @staticmethod
    def _cycle_start(
        reading_date: date,
        billing_start: date,
        cycle_months: int,
    ) -> datetime:
        months_since_start = (
            (reading_date.year - billing_start.year) * 12
            + reading_date.month
            - billing_start.month
        )
        periods_since_start = months_since_start // cycle_months
        candidate = billing_start + relativedelta(months=periods_since_start * cycle_months)
        if candidate > reading_date:
            candidate -= relativedelta(months=cycle_months)
        return datetime.combine(candidate, time.min)

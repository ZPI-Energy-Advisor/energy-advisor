from datetime import date, datetime, time
from decimal import Decimal
import logging
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from dateutil.relativedelta import relativedelta

from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.repositories.tariff_definition_repository import TariffDefinitionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.calculation import AnnualConsumption, CalculationDetails, PVDetails, TariffData, UnsupportedTariffInfo
from app.schemas.other import BillingCycleEnum, PVTypeEnum, TariffTypeEnum, TypeOfMarketEnergyEnum
from app.schemas.user_profile import UserProfile
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
from app.services.tariff_zones import ZoneSchedule


logger = logging.getLogger(__name__)


def _polish_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


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
    ):
        self.user_repository = user_repository
        self.energy_file_repository = energy_file_repository
        self.energy_reading_repository = energy_reading_repository
        self.tariff_repository = tariff_repository
        market_prices = (
            DynamicMarketPriceResolver(market_price_repository) if market_price_repository is not None else None
        )
        self.pv_balancer = pv_balancer or PVBalancingEngine(market_prices)
        self.tariff_engine = tariff_engine or ZonedTariffCalculationStrategy()
        if market_prices is not None:
            # Ceny RCE z tej samej pamięci podręcznej co net-billing (wczytywane miesiącami, nie kwadransami).
            self.tariff_engine.set_dynamic_price_resolver(
                lambda timestamp: market_prices(timestamp, TypeOfMarketEnergyEnum.RCE)
            )
        self.settlement = settlement or FinancialSettlement()

    def _load_inputs(self, user_id: UUID, file_id: UUID, readings=None):
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
        tariff_data = TariffData(
            tariff_type=profile_data.consumption_and_tariff.tariff_type,
            dynamic_price=profile_data.consumption_and_tariff.dynamic_price,
            billing_cycle=base_info.billing_cycle,
            billing_period_start_date=base_info.billing_period_start_date,
            distribution_operator=base_info.distribution_operator,
            phase_type=base_info.phase_type,
            contracted_power_kw=base_info.contracted_power_kw,
        )
        if readings is None:
            readings = self.energy_reading_repository.list_for_file(file_id)
        if not readings:
            raise HTTPException(status_code=409, detail="Brak surowych odczytów energii dla pliku.")
        return profile_data, tariff_data, readings

    def _details(self, profile_data, tariff_data, readings, first_day, warnings) -> CalculationDetails:
        if first_day is not None:
            readings = [reading for reading in readings if reading.measured_at.date() >= first_day]
        used_energy_cycles, produced_energy_cycles = self._cycles_from_readings(readings, tariff_data)

        pv_details = self._build_pv_details(profile_data.pv_config, produced_energy_cycles)
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

    def perform_tariff_calculations(
        self, user_id: UUID, file_id: UUID, readings=None, selected_only: bool = False
    ) -> CalculationDetails:
        """Rachunki dla pliku; `readings` zastępuje odczyty z bazy (np. zużycie po przesunięciu akcji),
        `selected_only` liczy tylko taryfę z profilu (grupa albo grupa z ceną dynamiczną)."""
        profile_data, tariff_data, readings = self._load_inputs(user_id, file_id, readings)
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

        base_details = self._details(profile_data, tariff_data, readings, first_day, warnings)
        consumption = base_details.annual_consumption
        context = BillingContext(
            regulatory_periods=regulatory_periods,
            annual_kwh=Decimal(str(consumption.annual_kwh)),
            first_day=first_day,
            last_day=file_last,
            raw_cycles=base_details.used_energy_cycles,
            prosumer=base_details.pv_details is not None,
        )
        # Taryfy strefowe po kodzie; oferta dynamiczna osobno dla każdej grupy dystrybucyjnej.
        definitions_by_key: dict[tuple[TariffTypeEnum, TariffTypeEnum], list] = {}
        for definition in definitions:
            key = (definition.tariff_code, definition.distribution_group)
            definitions_by_key.setdefault(key, []).append(definition)

        calculations = {}
        dynamic_calculations = {}
        calculation_errors = {}
        tariff_notes = {}
        selected_key = (
            (TariffTypeEnum.DYNAMIC, tariff_data.tariff_type) if tariff_data.dynamic_price
            else (tariff_data.tariff_type, tariff_data.tariff_type)
        )
        for (tariff_code, group), tariff_definitions in definitions_by_key.items():
            if selected_only and (tariff_code, group) != selected_key:
                continue
            dynamic = tariff_code == TariffTypeEnum.DYNAMIC
            tariff_name = f"dynamic {group.value}" if dynamic else tariff_code.value
            note_key = tariff_code.value
            available_from = min(definition.valid_from for definition in tariff_definitions)
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
                details = base_details.model_copy(deep=True)
                details.tariff_data.tariff_type = tariff_code
                months = billing_cycle_months(tariff_definitions, profile_months)
                if months != profile_months:
                    # Oferta wymaga własnego okresu (np. 1 miesiąc) niezależnie od okresu z profilu.
                    details.tariff_data.billing_cycle = BillingCycleEnum(months)
                    cycle_details = self._details(profile_data, details.tariff_data, readings, first_day, warnings)
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
            raise HTTPException(
                status_code=409,
                detail="Brak kompletnych danych taryfowych dla tego pliku. "
                + " ".join(f"{name}: {error}" for name, error in calculation_errors.items()),
            )
        selected_group = base_details.tariff_data.tariff_type.value
        base_details.tariff_calculations = calculations
        base_details.dynamic_calculations = dynamic_calculations or None
        base_details.tariff_calculation_errors = calculation_errors or None
        selected = dynamic_calculations if base_details.tariff_data.dynamic_price else calculations
        base_details.tariff_calculation = selected.get(selected_group)
        base_details.tariff_notes = tariff_notes or None
        base_details.unsupported_tariffs = [
            UnsupportedTariffInfo(code=item.tariff_code, name=item.name, reason=item.reason)
            for item in self._unique_unsupported(
                self.tariff_repository.list_unsupported(operator=operator, date_from=first_day, date_to=file_last)
            )
        ] or None
        return base_details

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
        for reading in readings:
            timestamp = reading.measured_at
            used = float(reading.energy_kwh)
            produced = float(reading.exported_kwh)
            cycle_start = CalculationsService._cycle_start(
                timestamp.date(),
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
        mode = pv_config.get("mode") if isinstance(pv_config, dict) else pv_config.mode
        if mode == "none":
            return None

        details = {
            "pv_energy_cycles": produced_energy_cycles,
            "mode": mode,
        }
        if mode == "net_metering":
            details["power_of_pv_kwp"] = (
                pv_config.get("power_of_pv_kwp")
                if isinstance(pv_config, dict)
                else pv_config.power_of_pv_kwp
            )
        else:
            details["type_of_market_energy"] = TypeOfMarketEnergyEnum.RCE
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

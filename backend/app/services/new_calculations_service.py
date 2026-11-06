from datetime import date, datetime, time
from decimal import Decimal
import logging
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from dateutil.relativedelta import relativedelta

from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.repositories.tariff_definition_repository import TariffDefinitionRepository
from app.repositories.user_repository import UserRepository
from app.schemas.calculation import AnnualConsumption, CalculationDetails, PVDetails, TariffData
from app.schemas.other import TariffTypeEnum
from app.schemas.user_profile import UserProfile
from app.services.pv_service import DynamicMarketPriceResolver, PVBalancingEngine
from app.services.tariff_engine import (
    DAYS_IN_YEAR,
    BillingContext,
    FinancialSettlement,
    ZonedTariffCalculationStrategy,
    covers,
    days_between,
    format_day_ranges,
)


logger = logging.getLogger(__name__)


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
        self.pv_balancer = pv_balancer or PVBalancingEngine(
            DynamicMarketPriceResolver(market_price_repository)
            if market_price_repository is not None
            else None
        )
        self.tariff_engine = tariff_engine or ZonedTariffCalculationStrategy()
        if market_price_repository is not None:
            def dynamic_price(timestamp):
                # Odczyty są zapisane w czasie lokalnym bez strefy, a ceny RCE w UTC.
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=LOCAL_TIMEZONE)
                prices = market_price_repository.get_prices_between(
                    "pse_rce", timestamp, timestamp + relativedelta(minutes=15)
                )
                if not prices:
                    raise ValueError(f"Brak ceny RCE dla interwału {timestamp.isoformat()}.")
                return float(next(iter(prices.values()))) / 1000.0

            self.tariff_engine.set_dynamic_price_resolver(
                dynamic_price
            )
        self.settlement = settlement or FinancialSettlement()


    def compute_calculation_details(self, user_id: UUID, file_id: UUID) -> CalculationDetails:
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
        consumption = profile_data.consumption_and_tariff
        tariff_data = TariffData(
            tariff_type=consumption.tariff_type,
            billing_cycle=base_info.billing_cycle,
            billing_period_start_date=base_info.billing_period_start_date,
            distribution_operator=base_info.distribution_operator,
            phase_type=base_info.phase_type,
            contracted_power_kw=base_info.contracted_power_kw,
        )

        readings = self.energy_reading_repository.list_for_file(file_id)
        used_energy_cycles, produced_energy_cycles = self._cycles_from_readings(readings, tariff_data)

        pv_details = self._build_pv_details(profile_data.pv_config, produced_energy_cycles)
        warnings = []
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


    def perform_tariff_calculations(self, user_id: UUID, file_id: UUID) -> CalculationDetails:
        base_details = self.compute_calculation_details(user_id, file_id)
        consumption = base_details.annual_consumption
        first_day, last_day = consumption.data_start, consumption.data_end
        operator = base_details.tariff_data.distribution_operator
        definitions = self.tariff_repository.list_for_period(
            operator=operator, date_from=first_day, date_to=last_day
        )
        if not definitions:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Brak stawek taryfowych operatora {operator.value} dla okresu pliku "
                    f"{first_day.isoformat()} – {last_day.isoformat()}."
                ),
            )
        regulatory_periods = self.tariff_repository.list_regulatory_periods(date_from=first_day, date_to=last_day)
        missing_days = [
            day for day in days_between(first_day, last_day)
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
        context = BillingContext(
            regulatory_periods=regulatory_periods,
            annual_kwh=Decimal(str(consumption.annual_kwh)),
            first_day=first_day,
            last_day=last_day,
            raw_cycles=base_details.used_energy_cycles,
        )
        definitions_by_code = {}
        for definition in definitions:
            definitions_by_code.setdefault(definition.tariff_code, []).append(definition)

        calculations = {}
        calculation_errors = {}
        for tariff_code, tariff_definitions in definitions_by_code.items():
            tariff_name = tariff_code.value
            try:
                details = base_details.model_copy(deep=True)
                details.tariff_data.tariff_type = TariffTypeEnum(tariff_name)
                if details.pv_details is not None:
                    details = self.pv_balancer.balance_pv(details)
                result = self.tariff_engine.calculate(details, tariff_definitions, context)
                result = self.settlement.settle(result, details.overpayment_cycles)
                calculations[tariff_name] = result.as_dict()
            except (ValueError, KeyError) as exc:
                calculation_errors[tariff_name] = str(exc)
                logger.warning(
                    "Skipping tariff %s for file %s: %s",
                    tariff_name,
                    file_id,
                    exc,
                )

        selected_name = base_details.tariff_data.tariff_type.value
        if not calculations:
            raise HTTPException(
                status_code=409,
                detail="Brak kompletnych danych taryfowych dla tego pliku.",
            )
        base_details.tariff_calculations = calculations
        base_details.tariff_calculation_errors = calculation_errors or None
        base_details.tariff_calculation = calculations.get(selected_name)
        return base_details

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
        """Pobór z sieci w pliku przeskalowany do roku (próg opłaty mocowej i przejściowej)."""
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
            details["type_of_market_energy"] = (
                pv_config.get("type_of_price")
                if isinstance(pv_config, dict)
                else pv_config.type_of_price
            )
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

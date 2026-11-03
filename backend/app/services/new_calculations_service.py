from datetime import date, datetime, time
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
from app.schemas.calculation import CalculationDetails, PVDetails, TariffData
from app.schemas.other import TariffTypeEnum
from app.schemas.user_profile import UserProfile
from app.services.pv_service import DynamicMarketPriceResolver, PVBalancingEngine
from app.services.tariff_engine import FinancialSettlement, ZonedTariffCalculationStrategy


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

        used_energy_cycles, produced_energy_cycles = self._cycles_from_readings(
            self.energy_reading_repository.list_for_file(file_id),
            tariff_data,
        )

        pv_details = self._build_pv_details(profile_data.pv_config, produced_energy_cycles)

        return CalculationDetails(
            pv_details=pv_details,
            used_energy_cycles=used_energy_cycles,
            tariff_data=tariff_data,
        )


    def perform_tariff_calculations(self, user_id: UUID, file_id: UUID) -> CalculationDetails:
        base_details = self.compute_calculation_details(user_id, file_id)
        definitions = self.tariff_repository.list_for_calculation(
            operator=base_details.tariff_data.distribution_operator,
            calculation_date=base_details.tariff_data.billing_period_start_date,
        )
        if not definitions:
            raise HTTPException(
                status_code=409,
                detail="Brak stawek taryfowych dla wybranego operatora i daty.",
            )

        calculations = {}
        calculation_errors = {}
        for definition in definitions:
            tariff_name = definition.tariff_code.value
            try:
                details = base_details.model_copy(deep=True)
                details.tariff_data.tariff_type = TariffTypeEnum(tariff_name)
                if details.pv_details is not None:
                    details = self.pv_balancer.balance_pv(details)
                result = self.tariff_engine.calculate(details, definition)
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
            value = float(reading.energy_kwh)
            cycle_start = CalculationsService._cycle_start(
                timestamp.date(),
                tariff_data.billing_period_start_date,
                tariff_data.billing_cycle.value,
            )
            cycle_starts.add(cycle_start)
            if value > 0:
                used_cycles.setdefault(cycle_start, []).append((timestamp, value))
            elif value < 0:
                produced_cycles.setdefault(cycle_start, []).append((timestamp, abs(value)))

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
    def _build_pv_details(pv_config, produced_energy_cycles):
        mode = pv_config.get("mode") if isinstance(pv_config, dict) else pv_config.mode
        if mode == "none":
            if any(records for _, records in produced_energy_cycles):
                raise HTTPException(
                    status_code=409,
                    detail="Plik zawiera produkcję energii, ale profil nie ma skonfigurowanej instalacji PV.",
                )
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

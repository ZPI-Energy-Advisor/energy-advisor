import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from app.models.EnergyDataFile import EnergyDataFile
from app.models.User import User
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.simulation_repository import SimulationRepository
from app.services.home_service import HomeService
from app.services.calculation_service import (
    ACTIONS_PER_DAY_KEY,
    IMPORT_REPORT_KEY,
    CalculationService,
    has_usage_series,
    public_results,
    source_resolution,
)
from app.schemas.schedule import ChargingPeriodOut, ScheduledActionOut, SchedulePriceOut, ScheduleResponse
from app.services.pricing_strategies import SLOT_MINUTES
from app.services.scheduling import INTERRUPTIBLE, SLOT, actions_from_devices, load_from_devices, schedule
from app.schemas.calculation import TariffChoice
from app.services.schedule_prices import SchedulePriceService
from app.services.schedule_bill import grid_limit_note, padded_readings, shifted_readings
from app.schemas.tariff_comparison import TariffComparisonResponse
from app.services.new_calculations_service import profile_key
from app.services.tariff_comparison import Reading, comparison, readings_from_usage, tariff_entries
from app.services.tariff_costs import TariffCostService, tariff_key, tariff_label
from app.schemas.energy_file import (
    ALL_DEVICE_FILES_SOURCE_ID,
    ALL_DEVICE_FILES_SOURCE_NAME,
    ALL_FILES_SOURCE_ID,
    ALL_FILES_SOURCE_NAME,
    AggregateSourceFile,
    AggregateSourceOut,
    AggregateSourceSummary,
    EnergyDataFileDataResponse,
    EnergyDataFileListResponse,
    EnergyDataFileOut,
)



EARLIEST = datetime(1970, 1, 1, tzinfo=timezone.utc)
LATEST = datetime(9999, 1, 1, tzinfo=timezone.utc)

AGGREGATE_SOURCES = {
    EnergyDataFile.SOURCE_METER: (ALL_FILES_SOURCE_ID, ALL_FILES_SOURCE_NAME, "plików z licznika"),
    EnergyDataFile.SOURCE_DEVICES: (ALL_DEVICE_FILES_SOURCE_ID, ALL_DEVICE_FILES_SOURCE_NAME, "plików urządzeń"),
}
AGGREGATE_SOURCE_TYPES = {source_id: source_type for source_type, (source_id, _, _) in AGGREGATE_SOURCES.items()}
LEGACY_FIELDS = (
    "key", "label", "name", "type", "tariff_code", "distribution_group", "is_profile", "note", "billing_cycle_months",
    "energy_cost_pln", "monthly_fees_pln", "monthly_fee_gross", "cost_breakdown",
)


@dataclass(frozen=True)
class _ReadingsSource:
    file_ids: list[UUID] | None = None
    exports: dict | None = None

    @classmethod
    def of_aggregate(cls, source_type: str, aggregate: "_Aggregate") -> "_ReadingsSource":
        if source_type == EnergyDataFile.SOURCE_DEVICES:
            return cls(exports=aggregate.exports)
        return cls(file_ids=[energy_file.id for energy_file in aggregate.files])


@dataclass
class _Aggregate:
    files: list
    skipped_files: list
    usage: dict
    contributions: list
    actions_per_day: dict | None
    exports: dict | None
    resolution: int | None
    records_count: int

    @property
    def data_start(self) -> date:
        return date.fromisoformat(min(self.usage))

    @property
    def data_end(self) -> date:
        return date.fromisoformat(max(self.usage))


class EnergyFileService:
    def __init__(
        self,
        file_repository: EnergyDataFileRepository,
        simulation_repository: SimulationRepository,
        device_repository: DeviceRepository,
        schedule_prices: SchedulePriceService,
        calculations_service=None,
        home_service: HomeService | None = None,
        tariff_costs: TariffCostService | None = None,
    ):
        self.file_repository = file_repository
        self.simulation_repository = simulation_repository
        self.device_repository = device_repository
        self.schedule_prices = schedule_prices
        self.calculations_service = calculations_service
        self.home_service = home_service
        self.tariff_costs = tariff_costs

    def _priced_results(
        self, user_id: UUID, results: dict, date_from: date, date_to: date, all_tariffs: bool = True,
        source: _ReadingsSource | None = None,
    ) -> dict:
        """Wykresy, statystyki i rachunek taryfy z profilu dla dni [date_from, date_to], z cenami policzonymi
        teraz z cennika; `all_tariffs` dodaje do wykresów ceny wszystkich taryf operatora."""
        usage = CalculationService.usage_in_range(results["usage_15min"], date_from, date_to)
        tariffs, pricing = {}, None
        if self.calculations_service is not None:
            readings = self._engine_readings(source or _ReadingsSource(), usage, date_from, date_to)
            tariffs, pricing = self._usage_tariffs(user_id, readings, date_from, all_tariffs)
        slot_prices = {}
        if self.tariff_costs is not None and (tariffs or all_tariffs):
            slot_prices = self.tariff_costs.chart_prices(
                self.tariff_costs.profile(user_id), usage, None if all_tariffs else tariffs
            )
        summary = CalculationService.summarize_usage(
            usage, slot_prices, source_resolution(results), results.get(ACTIONS_PER_DAY_KEY)
        )
        summary["tariffs"] = tariffs
        summary["pricing"] = pricing
        return summary

    def _engine_readings(self, source: _ReadingsSource, usage: dict, date_from: date, date_to: date) -> list:
        if source.file_ids:
            rows = self.calculations_service.energy_reading_repository.merged_for_files(
                source.file_ids, datetime.combine(date_from, time()), datetime.combine(date_to + timedelta(days=1), time()),
            )
            if rows:
                return [Reading(*row) for row in rows]
        return readings_from_usage(usage, source.exports)

    def _calculate(self, user_id: UUID, readings: list, inputs, all_tariffs: bool):
        return self.calculations_service.calculate(
            readings, inputs, selected_only=not all_tariffs, fallback=True, user_id=user_id,
        )

    def _usage_tariffs(self, user_id: UUID, readings: list, first_day: date, all_tariffs: bool) -> tuple[dict, dict]:
        inputs = self.calculations_service.profile_inputs(user_id, first_day)
        pricing = {
            "operator": inputs.tariff_data.distribution_operator.value,
            "from_profile": inputs.from_profile,
            "profile_tariff": tariff_key(*profile_key(inputs.tariff_data)),
            "tariff_key": None,
            "tariff_label": None,
            "note": None,
            "all_tariffs": all_tariffs,
        }
        if not readings:
            return {}, pricing
        try:
            run = self._calculate(user_id, readings, inputs, all_tariffs=False)
        except HTTPException as error:
            return {}, {**pricing, "note": str(error.detail)}
        total_usage = round(run.details.annual_consumption.consumption_kwh, 2)
        tariffs = {
            entry["key"]: {
                **{name: entry.get(name) for name in LEGACY_FIELDS},
                "total_usage_kwh": total_usage,
                "estimated_cost_pln": entry["payable_gross"],
            }
            for entry in tariff_entries(run)
        }
        notes = [*(run.details.warnings or []), run.selection_note]
        return tariffs, {
            **pricing,
            "tariff_key": tariff_key(*run.selected_key),
            "tariff_label": tariff_label(*run.selected_key),
            "note": " ".join(note for note in notes if note) or None,
        }

    def get_tariff_comparison(
        self, source_id: str, user_id: UUID, date_from: date | None = None, date_to: date | None = None,
        all_tariffs: bool = True,
    ) -> TariffComparisonResponse:
        if source_id in AGGREGATE_SOURCE_TYPES:
            source_type = AGGREGATE_SOURCE_TYPES[source_id]
            aggregate = self._aggregate(user_id, source_type)
            usage, data_start, data_end = aggregate.usage, aggregate.data_start, aggregate.data_end
            source = _ReadingsSource.of_aggregate(source_type, aggregate)
            source_name = AGGREGATE_SOURCES[source_type][1]
        else:
            try:
                file_id = UUID(source_id)
            except ValueError as error:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono pliku.") from error
            energy_file, simulation = self._completed_file(file_id, user_id)
            usage, data_start, data_end = simulation.results["usage_15min"], energy_file.data_start, energy_file.data_end
            source_type, source_name = energy_file.source_type, energy_file.file_name
            source = _ReadingsSource(file_ids=[energy_file.id])
        date_from, date_to = self._resolve_range(data_start, data_end, date_from, date_to)
        usage = CalculationService.usage_in_range(usage, date_from, date_to)
        readings = self._engine_readings(source, usage, date_from, date_to)
        inputs = self.calculations_service.profile_inputs(user_id, date_from)
        return TariffComparisonResponse(
            source_id=source_id,
            source_name=source_name,
            source_type=source_type,
            date_from=date_from,
            date_to=date_to,
            all_tariffs=all_tariffs,
            **comparison(self._calculate(user_id, readings, inputs, all_tariffs)),
        )

    def list_files(self, user_id: UUID, page: int, page_size: int) -> EnergyDataFileListResponse:
        items, total = self.file_repository.list_by_user_id(
            user_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return EnergyDataFileListResponse(
            items=[EnergyDataFileOut.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=math.ceil(total / page_size),
            **self._aggregate_summaries(user_id),
        )

    def _aggregate_summaries(self, user_id: UUID) -> dict[str, AggregateSourceSummary | None]:
        summaries = self.file_repository.get_completed_summaries(user_id)
        return {
            "aggregate": self._aggregate_summary(EnergyDataFile.SOURCE_METER, summaries),
            "devices_aggregate": self._aggregate_summary(EnergyDataFile.SOURCE_DEVICES, summaries),
        }

    @staticmethod
    def _aggregate_summary(source_type: str, summaries: dict) -> AggregateSourceSummary | None:
        if source_type not in summaries:
            return None
        files_count, data_start, data_end = summaries[source_type]
        source_id, source_name, _ = AGGREGATE_SOURCES[source_type]
        return AggregateSourceSummary(
            id=source_id,
            file_name=source_name,
            source_type=source_type,
            files_count=files_count,
            data_start=data_start,
            data_end=data_end,
        )

    def _completed_file(self, file_id: UUID, user_id: UUID) -> tuple[EnergyDataFile, Any]:
        energy_file = self._get_own_file(file_id, user_id)
        simulation = self.simulation_repository.get_latest_by_file_id(energy_file.id)
        if energy_file.status != EnergyDataFile.STATUS_COMPLETED or not simulation:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Dane pliku nie są dostępne (status: {energy_file.status}).",
            )
        if not has_usage_series(simulation.results):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ten plik został wgrany w starszej wersji aplikacji, która nie zapisywała zużycia w kwadransach. "
                "Wgraj go ponownie, aby zobaczyć wykresy i koszty.",
            )
        return energy_file, simulation

    def get_file_data(
        self,
        file_id: UUID,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        all_tariffs: bool = True,
    ) -> EnergyDataFileDataResponse:
        energy_file, simulation = self._completed_file(file_id, user_id)
        if date_from is None and date_to is None:
            date_from, date_to = energy_file.data_start, energy_file.data_end
        else:
            date_from, date_to = self._resolve_range(energy_file.data_start, energy_file.data_end, date_from, date_to)
        results = self._priced_results(
            user_id, simulation.results, date_from, date_to, all_tariffs, _ReadingsSource(file_ids=[energy_file.id]),
        )

        return EnergyDataFileDataResponse(
            status="success",
            file=EnergyDataFileOut.model_validate(energy_file),
            simulation_id=str(simulation.id),
            created_at=simulation.created_at,
            date_from=date_from,
            date_to=date_to,
            import_report=simulation.results.get(IMPORT_REPORT_KEY),
            results=public_results(results),
        )

    def _aggregate(self, user_id: UUID, source_type: str) -> _Aggregate:
        files_label = AGGREGATE_SOURCES[source_type][2]
        files = self.file_repository.list_completed_by_user_id(user_id, source_type)
        simulations = self.simulation_repository.get_latest_by_file_ids([file.id for file in files])

        merged_files, sources, skipped_files = [], [], []
        for energy_file in files:
            simulation = simulations.get(energy_file.id)
            if simulation and has_usage_series(simulation.results):
                merged_files.append(energy_file)
                sources.append(simulation.results)
            else:
                skipped_files.append(energy_file)

        if not sources:
            detail = (
                "Twoje pliki zostały wgrane przed wprowadzeniem łączenia danych. Wgraj je ponownie."
                if skipped_files
                else f"Nie masz jeszcze poprawnie zaimportowanych {files_label}."
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

        resolutions = [source_resolution(source) for source in sources]
        actions_per_day = exports = None
        if source_type == EnergyDataFile.SOURCE_DEVICES:
            usage, actions_per_day, contributions, exports = self._merge_device_files(merged_files, sources)
            records_count = sum(actions_per_day.values())
        else:
            usage, contributions = CalculationService.merge_usage(sources)
            records_count = round(sum(
                contribution["slots_used"] * SLOT_MINUTES / resolution
                for contribution, resolution in zip(contributions, resolutions)
            ))
        return _Aggregate(
            files=merged_files,
            skipped_files=skipped_files,
            usage=usage,
            contributions=contributions,
            actions_per_day=actions_per_day,
            exports=exports,
            resolution=resolutions[0] if len(set(resolutions)) == 1 else None,
            records_count=records_count,
        )

    def get_all_files_data(
        self,
        user_id: UUID,
        source_type: str = EnergyDataFile.SOURCE_METER,
        date_from: date | None = None,
        date_to: date | None = None,
        all_tariffs: bool = True,
    ) -> EnergyDataFileDataResponse:
        """Dane zbiorcze ze wszystkich poprawnie zaimportowanych plików użytkownika.

        Nie są nigdzie zapisywane - liczymy je przy każdym zapytaniu z serii zapisanych przy
        imporcie, więc dodanie lub usunięcie pliku od razu zmienia wynik.
        """
        source_id, source_name, _ = AGGREGATE_SOURCES[source_type]
        aggregate = self._aggregate(user_id, source_type)
        merged_results = {"statistics": {"resolution_minutes": aggregate.resolution}, "usage_15min": aggregate.usage}
        if source_type == EnergyDataFile.SOURCE_DEVICES:
            merged_results[ACTIONS_PER_DAY_KEY] = aggregate.actions_per_day

        data_start, data_end = aggregate.data_start, aggregate.data_end
        if date_from is None and date_to is None:
            date_from, date_to = data_start, data_end
        else:
            date_from, date_to = self._resolve_range(data_start, data_end, date_from, date_to)

        source = AggregateSourceOut(
            id=source_id,
            file_name=source_name,
            source_type=source_type,
            data_start=data_start,
            data_end=data_end,
            records_count=aggregate.records_count,
            files_count=len(aggregate.files),
            files=[
                self._aggregate_file(energy_file, **contribution)
                for energy_file, contribution in zip(aggregate.files, aggregate.contributions)
            ],
            skipped_files=[
                self._aggregate_file(energy_file, days_used=0, slots_used=0) for energy_file in aggregate.skipped_files
            ],
        )

        return EnergyDataFileDataResponse(
            status="success",
            file=source,
            date_from=date_from,
            date_to=date_to,
            results=public_results(
                self._priced_results(
                    user_id, merged_results, date_from, date_to, all_tariffs,
                    _ReadingsSource.of_aggregate(source_type, aggregate),
                )
            ),
        )

    def _readings_in_range(self, file_id: UUID, date_from: date, date_to: date) -> list:
        """Odczyty dób [date_from, date_to]; baza zwraca tylko ten zakres, a nie cały plik."""
        if self.calculations_service is None:
            return []
        return self.calculations_service.energy_reading_repository.list_for_file_between(
            file_id, datetime.combine(date_from, time()), datetime.combine(date_to + timedelta(days=1), time()),
        )

    @staticmethod
    def _bill_readings(readings: list, date_to: date, latest_end: datetime) -> list:
        """Odczyty okresu i jego ogona do końca najpóźniejszej akcji (przed albo po optymalizacji).

        `readings` to odczyty okresu z dobą po nim. Akcja zaczęta w okresie może skończyć się po północy ostatniej
        doby, a ładowanie EV może się tam przenieść: jej energia należy do okresu, więc rachunek „przed” i „po”
        liczy te same kwadranse ogona.
        """
        tail_end = latest_end.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)
        return [
            reading for reading in readings
            if reading.measured_at.date() <= date_to or reading.measured_at < tail_end
        ]

    def _bills(self, user_id: UUID, file_id: UUID, readings: list, actions, tariff: TariffChoice | None = None) -> dict:
        """Pełny rachunek taryfy przed i po przesunięciu akcji (ten sam silnik co Wyniki kalkulacji).
        Taryfa z profilu albo wybrana na ekranie (`tariff`)."""
        if self.calculations_service is None or not readings:
            return {}
        readings = padded_readings(readings, actions)
        try:
            before = self.calculations_service.perform_tariff_calculations(
                user_id, file_id, readings, selected_only=True, tariff=tariff,
            )
            after = self.calculations_service.perform_tariff_calculations(
                user_id, file_id, shifted_readings(readings, actions), selected_only=True, tariff=tariff,
            )
        except HTTPException as error:
            return {"bill_note": f"Nie udało się policzyć rachunku: {error.detail}"}
        if before.tariff_calculation is None or after.tariff_calculation is None:
            return {"bill_note": "Tej taryfy nie da się policzyć dla tego okresu, więc pokazujemy koszt akcji."}
        return {
            "bill_before": round(float(before.tariff_calculation["payable_gross"]), 2),
            "bill_after": round(float(after.tariff_calculation["payable_gross"]), 2),
        }

    def get_file_schedule(
        self, file_id: UUID, user_id: UUID, date_from: date | None, date_to: date | None,
        tariff: TariffChoice | None = None,
    ) -> ScheduleResponse:
        """Najtańsze rozmieszczenie akcji pliku urządzeń przy cenach kwadransów taryfy z profilu (nowy cennik)
        albo taryfy wybranej na ekranie (`tariff`, operator zawsze z profilu)."""
        energy_file = self._get_own_file(file_id, user_id)
        date_from, date_to = self._resolve_range(energy_file.data_start, energy_file.data_end, date_from, date_to)
        start = datetime.combine(date_from, time(), LOCAL_TIMEZONE).astimezone(timezone.utc)
        end = datetime.combine(date_to + timedelta(days=1), time(), LOCAL_TIMEZONE).astimezone(timezone.utc)

        # Jedno pobranie urządzeń z dobą przed i po okresie. Doby sąsiednie są tylko obciążeniem domu:
        # akcje z poprzedniej doby trwające po północy i urządzenia pracujące wtedy, gdy ładowanie EV
        # sięga za koniec okresu, liczą się do limitu przyłącza.
        around = self.device_repository.records_for_file(
            energy_file.id, user_id, start - timedelta(days=1), end + timedelta(days=1),
        )
        devices = [
            replace(device, actions=[action for action in device.actions if start <= action.start < end])
            for device in around
        ]
        neighbours = [
            replace(device, actions=[action for action in device.actions if not start <= action.start < end])
            for device in around
        ]
        actions = actions_from_devices(devices)
        if all(action.load_only for action in actions):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Optymalizacja działa tylko dla plików urządzeń z akcjami poboru energii w wybranym okresie.",
            )
        # Akcja może skończyć się po północy ostatniej doby, stąd ceny z zapasem jednej doby.
        # Jedno pobranie odczytów: okres i doba po nim (ogon rachunku z `_bill_readings`).
        readings_with_tail = self._readings_in_range(energy_file.id, date_from, date_to + timedelta(days=1))
        readings = [reading for reading in readings_with_tail if reading.measured_at.date() <= date_to]
        exports = {
            reading.measured_at.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc): float(reading.exported_kwh)
            for reading in readings
            if reading.exported_kwh and reading.exported_kwh > 0
        }
        pricing = self.schedule_prices.for_user(user_id, start, end + timedelta(days=1), exports, tariff)
        prices = pricing.prices
        result = schedule(actions + load_from_devices(neighbours), prices, max_grid_kw=pricing.max_grid_kw)

        missing_prices = [item for item in result.actions if item.cost_before is None]
        if len(missing_prices) == len(result.actions):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Brak cen taryfy {pricing.description} dla wybranego okresu, więc nie da się policzyć optymalizacji.",
            )

        # Akcja, która kończy się po ostatniej dobie, ma na wykresie także dobę z dokończeniem.
        latest_end = max(max(item.end, item.original_start + len(item.original_profile_kwh) * SLOT) for item in result.actions)
        prices_end = end + timedelta(days=1) if latest_end > end else end

        names = {device.device_id: device.name for device in devices}
        modes = {device.device_id: device.flexibility_mode for device in devices}
        programs = {
            (device.device_id, program.program_id): program.name for device in devices for program in device.programs
        }

        def local(moment: datetime) -> datetime:
            return moment.astimezone(LOCAL_TIMEZONE)

        bills = self._bills(
            user_id, energy_file.id, self._bill_readings(readings_with_tail, date_to, latest_end), result.actions, tariff,
        )
        if "bill_before" in bills and latest_end > end:
            # Ogon rachunku sięga najwyżej końca doby po okresie (tyle odczytów bierze `_bill_readings`).
            bills["bill_until"] = local(min(latest_end, end + timedelta(days=1)))

        # Przerwy pokazujemy tylko dla ładowania EV; zero w profilu innego urządzenia to część jego programu.
        sessions = {action.action_id for action in actions if action.mode == INTERRUPTIBLE}

        def charging(item) -> list[ChargingPeriodOut] | None:
            # Okresy ciągłego ładowania; None dla innych akcji i dla sesji bez przerw.
            if item.action_id not in sessions or all(item.profile_kwh):
                return None
            periods, period_start = [], None
            for index, kwh in enumerate([*item.profile_kwh, 0.0]):
                slot = item.start + index * SLOT
                if kwh and period_start is None:
                    period_start = slot
                elif not kwh and period_start is not None:
                    periods.append(ChargingPeriodOut(start=local(period_start), end=local(slot)))
                    period_start = None
            # Profil z samych zer (sesja EV bez energii): bez okresów, front pokaże zwykłe godziny start-end.
            return periods or None

        return ScheduleResponse(
            date_from=date_from,
            date_to=date_to,
            pricing=pricing.description,
            tariff_group=pricing.group.value if pricing.group else None,
            tariff_dynamic=pricing.dynamic,
            prosumer=pricing.prosumer,
            price_breakdown=getattr(pricing, "breakdown", None),
            pv_note=pricing.pv_note,
            max_grid_kw=pricing.max_grid_kw,
            grid_limit_note=grid_limit_note(readings, pricing.max_grid_kw),
            **bills,
            cost_before=round(result.cost_before, 2),
            cost_after=round(result.cost_after, 2),
            missing_price_actions=len(missing_prices),
            missing_price_days=sorted({local(item.original_start).date() for item in missing_prices}),
            actions=[
                ScheduledActionOut(
                    action_id=item.action_id,
                    device_id=item.device_id,
                    device_name=names[item.device_id],
                    flexibility_mode=modes.get(item.device_id),
                    program_name=programs.get((item.device_id, item.program_id)),
                    original_start=local(item.original_start),
                    original_end=local(item.original_start + len(item.original_profile_kwh) * SLOT),
                    start=local(item.start),
                    end=local(item.end),
                    energy_kwh=round(sum(item.profile_kwh), 2),
                    cost_before=None if item.cost_before is None else round(item.cost_before, 2),
                    cost_after=None if item.cost_after is None else round(item.cost_after, 2),
                    status=item.status,
                    reason=item.reason,
                    charging=charging(item),
                )
                for item in result.actions
            ],
            prices=[
                SchedulePriceOut(start=local(slot), price_pln_kwh=price)
                for slot, price in sorted(prices.items())
                if slot < prices_end
            ],
        )

    def _merge_device_files(self, files: list[EnergyDataFile], sources: list[dict]):
        """Scala pliki urządzeń według zapisanych flag superseded (zasada z ZP-79).

        Kwadrans urządzenia należy do najnowszego pliku, który zawiera to urządzenie i obejmuje ten
        kwadrans, więc sumowane są tylko wiersze z superseded = false.
        """
        file_ids = [energy_file.id for energy_file in files]
        covering = CalculationService.device_coverage([source["usage_15min"] for source in sources])
        balance = self.device_repository.merged_grid_balance(file_ids)
        usage = CalculationService.device_usage_series(covering, [(day, slot, used) for day, slot, used, _ in balance])
        exports = {(day, slot): float(exported) for day, slot, _, exported in balance if exported}
        actions_per_day = self.device_repository.merged_actions_per_day(file_ids)
        devices = self.device_repository.device_ids_by_file(file_ids)
        contributions = CalculationService.device_contributions(
            [devices.get(energy_file.id, set()) for energy_file in files], covering
        )
        return usage, actions_per_day, contributions, exports

    def delete_file(self, file_id: UUID, user: User) -> None:
        user_id = user.id
        energy_file = self._get_own_file(file_id, user_id)
        device_ids = list(self.device_repository.device_ids_by_file([energy_file.id]).get(energy_file.id, ()))
        # Plik sprzed zapisywania okresu: przeliczamy flagi jego urządzeń w całym czasie.
        period = (energy_file.period_start or EARLIEST, energy_file.period_end or LATEST)
        # Urządzenia obecne tylko w tym pliku znikają z domu, a kwadranse, które plik przykrywał,
        # wracają do obliczeń - wszystko w jednej transakcji.
        self.device_repository.delete_devices_only_in_file(user_id, energy_file.id)
        self.file_repository.delete_without_commit(energy_file)
        self.device_repository.refresh_superseded(user_id, device_ids, *period)
        self.file_repository.commit()
        if self.home_service:
            # Urządzenia obecne tylko w tym pliku zniknęły z domu, więc hub zatrzymuje ich mikroserwisy.
            self.home_service.sync_after_change(user)

    def _get_own_file(self, file_id: UUID, user_id: UUID) -> EnergyDataFile:
        # Cudzy plik zwraca 404 tak samo jak nieistniejący - nie zdradzamy, że istnieje.
        energy_file = self.file_repository.get_by_id_for_user(file_id, user_id)
        if not energy_file:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono pliku.")
        return energy_file

    @staticmethod
    def _aggregate_file(energy_file: EnergyDataFile, *, days_used: int, slots_used: int) -> AggregateSourceFile:
        return AggregateSourceFile(
            id=energy_file.id,
            file_name=energy_file.file_name,
            uploaded_at=energy_file.uploaded_at,
            data_start=energy_file.data_start,
            data_end=energy_file.data_end,
            days_used=days_used,
            slots_used=slots_used,
        )

    @staticmethod
    def _resolve_range(
        data_start: date | None,
        data_end: date | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[date, date]:
        if data_start is None or data_end is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Plik nie ma określonego zakresu dat.",
            )
        # Brakujący koniec zakresu oznacza granicę dostępnych danych.
        date_from = date_from or data_start
        date_to = date_to or data_end
        if date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Data początkowa nie może być późniejsza niż data końcowa.",
            )
        if date_from < data_start or date_to > data_end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Zakres musi mieścić się w okresie dostępnych danych "
                    f"({data_start:%d.%m.%Y} – {data_end:%d.%m.%Y})."
                ),
            )
        return date_from, date_to

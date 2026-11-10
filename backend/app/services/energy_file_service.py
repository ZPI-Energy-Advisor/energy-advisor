import math
from datetime import date, datetime, time, timedelta, timezone
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
from app.schemas.schedule import ScheduledActionOut, SchedulePriceOut, ScheduleResponse
from app.services.pricing_strategies import SLOT_MINUTES
from app.services.scheduling import SLOT, actions_from_devices, schedule
from app.services.schedule_prices import SchedulePriceService
from app.services.schedule_bill import shifted_readings
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


class EnergyFileService:
    def __init__(
        self,
        file_repository: EnergyDataFileRepository,
        simulation_repository: SimulationRepository,
        device_repository: DeviceRepository,
        schedule_prices: SchedulePriceService,
        calculations_service=None,
        home_service: HomeService | None = None,
    ):
        self.file_repository = file_repository
        self.simulation_repository = simulation_repository
        self.device_repository = device_repository
        self.schedule_prices = schedule_prices
        self.calculations_service = calculations_service
        self.home_service = home_service

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

    def get_file_data(
        self,
        file_id: UUID,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> EnergyDataFileDataResponse:
        energy_file = self._get_own_file(file_id, user_id)

        simulation = self.simulation_repository.get_latest_by_file_id(energy_file.id)
        if energy_file.status != EnergyDataFile.STATUS_COMPLETED or not simulation:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Dane pliku nie są dostępne (status: {energy_file.status}).",
            )

        results = simulation.results
        if date_from is None and date_to is None:
            date_from, date_to = energy_file.data_start, energy_file.data_end
        else:
            date_from, date_to = self._resolve_range(energy_file.data_start, energy_file.data_end, date_from, date_to)
            if not has_usage_series(results):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ten plik został wgrany przed wprowadzeniem filtrowania po datach. "
                    "Wgraj go ponownie, aby móc wybrać zakres.",
                )
            results = CalculationService.calculate_for_range(results, date_from, date_to)

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

    def get_all_files_data(
        self,
        user_id: UUID,
        source_type: str = EnergyDataFile.SOURCE_METER,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> EnergyDataFileDataResponse:
        """Dane zbiorcze ze wszystkich poprawnie zaimportowanych plików użytkownika.

        Nie są nigdzie zapisywane - liczymy je przy każdym zapytaniu z serii zapisanych przy
        imporcie, więc dodanie lub usunięcie pliku od razu zmienia wynik.
        """
        source_id, source_name, files_label = AGGREGATE_SOURCES[source_type]
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

        # Ceny stałe bierzemy z najnowszego importu (aktualny zestaw taryf), a ceny
        # dynamiczne łączymy po dniach, bo każdy plik ma ceny tylko dla swojego okresu.
        slot_prices = CalculationService.merge_slot_prices([source["slot_prices"] for source in sources])
        resolutions = [source_resolution(source) for source in sources]
        common_resolution = resolutions[0] if len(set(resolutions)) == 1 else None
        merged_results = {
            "slot_prices": slot_prices,
            "statistics": {"resolution_minutes": common_resolution},
        }
        if source_type == EnergyDataFile.SOURCE_DEVICES:
            usage, actions_per_day, contributions = self._merge_device_files(merged_files, sources)
            merged_results[ACTIONS_PER_DAY_KEY] = actions_per_day
            records_count = sum(actions_per_day.values())
        else:
            usage, contributions = CalculationService.merge_usage(sources)
            records_count = round(sum(
                contribution["slots_used"] * SLOT_MINUTES / resolution
                for contribution, resolution in zip(contributions, resolutions)
            ))
        merged_results["usage_15min"] = usage

        data_start, data_end = date.fromisoformat(min(usage)), date.fromisoformat(max(usage))
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
            records_count=records_count,
            files_count=len(merged_files),
            files=[
                self._aggregate_file(energy_file, **contribution)
                for energy_file, contribution in zip(merged_files, contributions)
            ],
            skipped_files=[self._aggregate_file(energy_file, days_used=0, slots_used=0) for energy_file in skipped_files],
        )

        return EnergyDataFileDataResponse(
            status="success",
            file=source,
            date_from=date_from,
            date_to=date_to,
            results=public_results(CalculationService.calculate_for_range(merged_results, date_from, date_to)),
        )

    def _readings_in_range(self, file_id: UUID, date_from: date, date_to: date) -> list:
        if self.calculations_service is None:
            return []
        readings = self.calculations_service.energy_reading_repository.list_for_file(file_id)
        return [reading for reading in readings if date_from <= reading.measured_at.date() <= date_to]

    def _bills(self, user_id: UUID, file_id: UUID, readings: list, actions) -> dict:
        """Pełny rachunek taryfy z profilu przed i po przesunięciu akcji (ten sam silnik co Wyniki kalkulacji)."""
        if self.calculations_service is None or not readings:
            return {}
        try:
            before = self.calculations_service.perform_tariff_calculations(
                user_id, file_id, readings, selected_only=True
            )
            after = self.calculations_service.perform_tariff_calculations(
                user_id, file_id, shifted_readings(readings, actions), selected_only=True
            )
        except HTTPException as error:
            return {"bill_note": f"Nie udało się policzyć rachunku: {error.detail}"}
        if before.tariff_calculation is None or after.tariff_calculation is None:
            return {"bill_note": "Taryfy z profilu nie da się policzyć dla tego okresu, więc pokazujemy koszt akcji."}
        return {
            "bill_before": round(float(before.tariff_calculation["payable_gross"]), 2),
            "bill_after": round(float(after.tariff_calculation["payable_gross"]), 2),
        }

    def get_file_schedule(
        self, file_id: UUID, user_id: UUID, date_from: date | None, date_to: date | None
    ) -> ScheduleResponse:
        """Najtańsze rozmieszczenie akcji pliku urządzeń przy cenach kwadransów taryfy z profilu (nowy cennik)."""
        energy_file = self._get_own_file(file_id, user_id)
        date_from, date_to = self._resolve_range(energy_file.data_start, energy_file.data_end, date_from, date_to)
        start = datetime.combine(date_from, time(), LOCAL_TIMEZONE).astimezone(timezone.utc)
        end = datetime.combine(date_to + timedelta(days=1), time(), LOCAL_TIMEZONE).astimezone(timezone.utc)

        devices = self.device_repository.records_for_file(energy_file.id, user_id, start, end)
        actions = actions_from_devices(devices)
        if not actions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Optymalizacja działa tylko dla plików urządzeń z akcjami poboru energii w wybranym okresie.",
            )
        # Akcja może skończyć się po północy ostatniej doby, stąd ceny z zapasem jednej doby.
        readings = self._readings_in_range(energy_file.id, date_from, date_to)
        exports = {
            reading.measured_at.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc): float(reading.exported_kwh)
            for reading in readings
            if reading.exported_kwh and reading.exported_kwh > 0
        }
        pricing = self.schedule_prices.for_user(user_id, start, end + timedelta(days=1), exports)
        prices = pricing.prices
        result = schedule(actions, prices)

        missing_prices = [item for item in result.actions if item.cost_before is None]
        if len(missing_prices) == len(result.actions):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Brak cen taryfy {pricing.description} dla wybranego okresu, więc nie da się policzyć optymalizacji.",
            )

        # Akcja, która kończy się po ostatniej dobie, ma na wykresie także dobę z dokończeniem.
        latest_end = max(max(item.end, item.original_start + len(item.profile_kwh) * SLOT) for item in result.actions)
        prices_end = end + timedelta(days=1) if latest_end > end else end

        names = {device.device_id: device.name for device in devices}
        programs = {
            (device.device_id, program.program_id): program.name for device in devices for program in device.programs
        }

        def local(moment: datetime) -> datetime:
            return moment.astimezone(LOCAL_TIMEZONE)

        return ScheduleResponse(
            date_from=date_from,
            date_to=date_to,
            pricing=pricing.description,
            **self._bills(user_id, energy_file.id, readings, result.actions),
            cost_before=round(result.cost_before, 2),
            cost_after=round(result.cost_after, 2),
            missing_price_actions=len(missing_prices),
            missing_price_days=sorted({local(item.original_start).date() for item in missing_prices}),
            actions=[
                ScheduledActionOut(
                    action_id=item.action_id,
                    device_id=item.device_id,
                    device_name=names[item.device_id],
                    program_name=programs.get((item.device_id, item.program_id)),
                    original_start=local(item.original_start),
                    original_end=local(item.original_start + len(item.profile_kwh) * SLOT),
                    start=local(item.start),
                    end=local(item.end),
                    energy_kwh=round(sum(item.profile_kwh), 2),
                    cost_before=None if item.cost_before is None else round(item.cost_before, 2),
                    cost_after=None if item.cost_after is None else round(item.cost_after, 2),
                    status=item.status,
                    reason=item.reason,
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
        usage = CalculationService.device_usage_series(covering, self.device_repository.merged_grid_import(file_ids))
        actions_per_day = self.device_repository.merged_actions_per_day(file_ids)
        devices = self.device_repository.device_ids_by_file(file_ids)
        contributions = CalculationService.device_contributions(
            [devices.get(energy_file.id, set()) for energy_file in files], covering
        )
        return usage, actions_per_day, contributions

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

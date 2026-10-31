import math
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status

from app.models.EnergyDataFile import EnergyDataFile
from app.providers.prices.base import MARKET_TIMEZONE
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.simulation_repository import SimulationRepository
from app.services.calculation_service import (
    IMPORT_REPORT_KEY,
    CalculationService,
    has_usage_series,
    public_results,
    source_resolution,
)
from app.schemas.schedule import ScheduledActionOut, SchedulePriceOut, ScheduleResponse
from app.services.dynamic_price_service import DynamicPriceService
from app.services.pricing_strategies import SLOT_MINUTES
from app.services.scheduling import SLOT, actions_from_devices, schedule
from app.schemas.energy_file import (
    AggregateSourceFile,
    AggregateSourceOut,
    AggregateSourceSummary,
    EnergyDataFileDataResponse,
    EnergyDataFileListResponse,
    EnergyDataFileOut,
)



class EnergyFileService:
    def __init__(
        self,
        file_repository: EnergyDataFileRepository,
        simulation_repository: SimulationRepository,
        device_repository: DeviceRepository,
        price_service: DynamicPriceService,
    ):
        self.file_repository = file_repository
        self.simulation_repository = simulation_repository
        self.device_repository = device_repository
        self.price_service = price_service

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
            aggregate=self._aggregate_summary(user_id),
        )

    def _aggregate_summary(self, user_id: UUID) -> AggregateSourceSummary | None:
        files_count, data_start, data_end = self.file_repository.get_completed_summary(user_id)
        if files_count == 0:
            return None
        return AggregateSourceSummary(files_count=files_count, data_start=data_start, data_end=data_end)

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
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> EnergyDataFileDataResponse:
        """Dane zbiorcze ze wszystkich poprawnie zaimportowanych plików użytkownika.

        Nie są nigdzie zapisywane - liczymy je przy każdym zapytaniu z serii zapisanych przy
        imporcie, więc dodanie lub usunięcie pliku od razu zmienia wynik.
        """
        files = self.file_repository.list_completed_by_user_id(user_id)
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
                else "Nie masz jeszcze poprawnie zaimportowanych plików."
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

        usage, contributions = CalculationService.merge_usage(sources)
        # Ceny stałe bierzemy z najnowszego importu (aktualny zestaw taryf), a ceny
        # dynamiczne łączymy po dniach, bo każdy plik ma ceny tylko dla swojego okresu.
        slot_prices = CalculationService.merge_slot_prices([source["slot_prices"] for source in sources])
        resolutions = [source_resolution(source) for source in sources]
        common_resolution = resolutions[0] if len(set(resolutions)) == 1 else None
        merged_results = {
            "usage_15min": usage,
            "slot_prices": slot_prices,
            "statistics": {"resolution_minutes": common_resolution},
        }

        data_start, data_end = date.fromisoformat(min(usage)), date.fromisoformat(max(usage))
        if date_from is None and date_to is None:
            date_from, date_to = data_start, data_end
        else:
            date_from, date_to = self._resolve_range(data_start, data_end, date_from, date_to)

        records_count = round(sum(
            contribution["slots_used"] * SLOT_MINUTES / resolution
            for contribution, resolution in zip(contributions, resolutions)
        ))

        source = AggregateSourceOut(
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

    def get_file_schedule(
        self, file_id: UUID, user_id: UUID, date_from: date | None, date_to: date | None
    ) -> ScheduleResponse:
        """Najtańsze rozmieszczenie akcji pliku urządzeń przy cenach taryfy dynamicznej."""
        energy_file = self._get_own_file(file_id, user_id)
        date_from, date_to = self._resolve_range(energy_file.data_start, energy_file.data_end, date_from, date_to)
        start = datetime.combine(date_from, time(), MARKET_TIMEZONE).astimezone(timezone.utc)
        end = datetime.combine(date_to + timedelta(days=1), time(), MARKET_TIMEZONE).astimezone(timezone.utc)

        devices = self.device_repository.records_for_file(energy_file.id, user_id, start, end)
        if not any(device.actions for device in devices):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Optymalizacja działa tylko dla plików urządzeń z akcjami w wybranym okresie.",
            )
        # Akcja może skończyć się po północy ostatniej doby, stąd ceny z zapasem jednej doby.
        prices = self.price_service.consumer_prices(start, end + timedelta(days=1))
        result = schedule(actions_from_devices(devices), prices)

        # Akcja, która kończy się po ostatniej dobie, ma na wykresie także dobę z dokończeniem.
        latest_end = max(max(item.end, item.original_start + len(item.profile_kwh) * SLOT) for item in result.actions)
        prices_end = end + timedelta(days=1) if latest_end > end else end

        names = {device.device_id: device.name for device in devices}
        programs = {
            (device.device_id, program.program_id): program.name for device in devices for program in device.programs
        }

        def local(moment: datetime) -> datetime:
            return moment.astimezone(MARKET_TIMEZONE)

        return ScheduleResponse(
            date_from=date_from,
            date_to=date_to,
            cost_before=round(result.cost_before, 2),
            cost_after=round(result.cost_after, 2),
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

    def delete_file(self, file_id: UUID, user_id: UUID) -> None:
        energy_file = self._get_own_file(file_id, user_id)
        # Urządzenia obecne tylko w tym pliku znikają z domu; commit robi usunięcie pliku.
        self.device_repository.delete_devices_only_in_file(user_id, energy_file.id)
        self.file_repository.delete(energy_file)

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

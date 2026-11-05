from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status

from app.models.DeviceInstance import DeviceInstance
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.repositories.simulation_repository import SimulationRepository
from app.schemas.device_usage import (
    DeviceUsageGroup,
    DeviceUsageGroupBy,
    DeviceUsageResolution,
    DeviceUsageResponse,
    DeviceUsageTariff,
    KwhSeries,
    RestOfHouse,
)
from app.schemas.energy_file import ALL_DEVICE_FILES_SOURCE_ID, ALL_FILES_SOURCE_ID
from app.services.calculation_service import CalculationService, has_usage_series
from app.services.user_service import UserService


SLOT = timedelta(minutes=15)
DEFAULT_TARIFF = "G11"
# Urządzenia, których pracę można przenieść na inne godziny (pralka, zmywarka, pompa ciepła, ładowarka EV).
FLEXIBLE_MODES = (DeviceInstance.SHIFTABLE, DeviceInstance.INTERRUPTIBLE)
EXCEEDED_TOLERANCE_SHARE = 0.01
EXCEEDED_TOLERANCE_MIN_KWH = 0.05


@dataclass
class _Source:
    """Pliki urządzeń, z których liczymy dane, i ich zapisane wyniki importu."""

    source_id: str
    files: list[EnergyDataFile]
    results: list[dict]
    current_only: bool


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), LOCAL_TIMEZONE).astimezone(timezone.utc)


def _local_slot(moment: datetime) -> tuple[str, int]:
    """Dzień lokalny i numer kwadransu doby, jak w seriach usage_15min i cennikach."""
    local = moment.astimezone(LOCAL_TIMEZONE)
    return local.date().isoformat(), local.hour * 4 + local.minute // 15


class _Axis:
    """Okresy wykresu: kwadranse, godziny albo doby lokalne między początkiem a końcem zakresu."""

    def __init__(self, date_from: date, date_to: date, resolution: DeviceUsageResolution):
        self.resolution = resolution
        start, end = _local_midnight(date_from), _local_midnight(date_to + timedelta(days=1))
        if resolution == DeviceUsageResolution.DAY:
            days = [date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]
            self.starts = [_local_midnight(day) for day in days]
        else:
            step = SLOT if resolution == DeviceUsageResolution.QUARTER else timedelta(hours=1)
            self.starts = [start + index * step for index in range(int((end - start) / step))]
        self.index = {self._key(moment): position for position, moment in enumerate(self.starts)}

    def _key(self, moment: datetime):
        if self.resolution == DeviceUsageResolution.DAY:
            return moment.astimezone(LOCAL_TIMEZONE).date()
        if self.resolution == DeviceUsageResolution.HOUR:
            # Polska strefa ma przesunięcie w pełnych godzinach, więc godziny lokalne i UTC się pokrywają.
            return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return moment.astimezone(timezone.utc)

    def position(self, slot_start: datetime) -> int:
        return self.index[self._key(slot_start)]

    def periods(self) -> list[datetime]:
        return [moment.astimezone(LOCAL_TIMEZONE) for moment in self.starts]


class _Accumulator:
    def __init__(self, size: int):
        self.kwh = [0.0] * size
        self.cost = [0.0] * size

    def add(self, position: int, kwh: float, price: float | None) -> None:
        self.kwh[position] += kwh
        if price is not None:
            self.cost[position] += kwh * price

    def series(self) -> dict:
        kwh = [round(value, 6) for value in self.kwh]
        cost = [round(value, 4) for value in self.cost]
        return {"kwh": kwh, "cost_pln": cost, "total_kwh": round(sum(self.kwh), 4), "total_cost_pln": round(sum(self.cost), 2)}


class DeviceUsageService:
    """Zużycie i koszt urządzeń w podziale na kategorie, typy albo pojedyncze urządzenia (ZP-81).

    Koszt kwadransu to jego zużycie razy cena tego kwadransu w wybranej taryfie z cennika zapisanego
    przy imporcie (slot_prices), tak jak koszt pliku na Dashboardzie.
    """

    def __init__(
        self,
        file_repository: EnergyDataFileRepository,
        simulation_repository: SimulationRepository,
        device_repository: DeviceRepository,
        reading_repository: EnergyReadingRepository,
        user_service: UserService,
    ):
        self.file_repository = file_repository
        self.simulation_repository = simulation_repository
        self.device_repository = device_repository
        self.reading_repository = reading_repository
        self.user_service = user_service

    def get_usage(
        self,
        source_id: str,
        user_id: UUID,
        *,
        group_by: DeviceUsageGroupBy = DeviceUsageGroupBy.CATEGORY,
        resolution: DeviceUsageResolution = DeviceUsageResolution.HOUR,
        date_from: date | None = None,
        date_to: date | None = None,
        tariff: str | None = None,
        category: str | None = None,
        device_type: str | None = None,
        flexible_only: bool = False,
        meter: str | None = None,
    ) -> DeviceUsageResponse:
        source = self._source(source_id, user_id)
        file_ids = [energy_file.id for energy_file in source.files]
        covering = CalculationService.device_coverage([results["usage_15min"] for results in source.results])
        covered_days = sorted({date.fromisoformat(day) for day, _ in covering})
        date_from, date_to = self._range(covered_days, date_from, date_to)
        start, end = _local_midnight(date_from), _local_midnight(date_to + timedelta(days=1))

        slot_prices = CalculationService.merge_slot_prices([results["slot_prices"] for results in source.results])
        tariff_info = self._tariff(user_id, tariff, slot_prices)
        price = self._price_lookup(slot_prices[tariff_info.name])

        rows = self.device_repository.slot_usage(file_ids, start, end, current_only=source.current_only)
        devices = {
            instance.id: (instance, type_label)
            for instance, type_label in self.device_repository.instances_with_type_labels(list({row[1] for row in rows}))
        }

        axis = _Axis(date_from, date_to, resolution)
        groups, members = defaultdict(lambda: _Accumulator(len(axis.starts))), defaultdict(set)
        production = _Accumulator(len(axis.starts))
        device_net = defaultdict(float)
        missing_price_slots = 0
        for slot_start, instance_id, kwh in rows:
            instance, _ = devices[instance_id]
            device_net[_local_slot(slot_start)] += kwh
            if not self._matches(instance, category, device_type, flexible_only):
                continue
            position = axis.position(slot_start)
            if kwh < 0:
                production.add(position, -kwh, None)
                continue
            slot_price = price(slot_start)
            missing_price_slots += slot_price is None and kwh > 0
            key = self._group_key(instance, group_by)
            groups[key].add(position, kwh, slot_price)
            members[key].add(instance_id)

        group_out = sorted(
            (self._group(key, groups[key], [devices[device_id] for device_id in members[key]], group_by) for key in groups),
            key=lambda group: (-group.total_kwh, group.label),
        )
        rest = None
        if meter is not None:
            rest = self._rest_of_house(
                meter, user_id, covering, device_net, start, end, date_from, date_to, axis, price
            )
        has_production = any(production.kwh)
        total_kwh = sum(group.total_kwh for group in group_out) + (rest.total_kwh if rest else 0.0)
        total_cost = sum(group.total_cost_pln for group in group_out) + (rest.total_cost_pln if rest else 0.0)
        return DeviceUsageResponse(
            source_id=source.source_id,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            resolution=resolution,
            tariff=tariff_info,
            periods=axis.periods(),
            groups=group_out,
            production=KwhSeries(**{key: production.series()[key] for key in ("kwh", "total_kwh")}) if has_production else None,
            rest_of_house=rest,
            total_kwh=round(total_kwh, 4),
            total_cost_pln=round(total_cost, 2),
            missing_price_slots=missing_price_slots,
        )

    def _source(self, source_id: str, user_id: UUID) -> _Source:
        if source_id == ALL_DEVICE_FILES_SOURCE_ID:
            files = self.file_repository.list_completed_by_user_id(user_id, EnergyDataFile.SOURCE_DEVICES)
            current_only = True
        else:
            energy_file = self._own_file(source_id, user_id)
            if energy_file.source_type != EnergyDataFile.SOURCE_DEVICES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Plik nie zawiera urządzeń. Podział na urządzenia jest dostępny dla plików urządzeń.",
                )
            if energy_file.status != EnergyDataFile.STATUS_COMPLETED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Dane pliku nie są dostępne (status: {energy_file.status}).",
                )
            files, current_only = [energy_file], False

        simulations = self.simulation_repository.get_latest_by_file_ids([energy_file.id for energy_file in files])
        pairs = [
            (energy_file, simulations[energy_file.id].results)
            for energy_file in files
            if energy_file.id in simulations and has_usage_series(simulations[energy_file.id].results)
        ]
        if not pairs:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nie masz jeszcze poprawnie zaimportowanych plików urządzeń.")
        return _Source(source_id, [pair[0] for pair in pairs], [pair[1] for pair in pairs], current_only)

    def _own_file(self, file_id: str, user_id: UUID) -> EnergyDataFile:
        try:
            parsed_id = UUID(file_id)
        except ValueError:
            parsed_id = None
        energy_file = self.file_repository.get_by_id_for_user(parsed_id, user_id) if parsed_id else None
        if energy_file is None:
            # Cudzy plik zwraca 404 tak samo jak nieistniejący.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono pliku.")
        return energy_file

    @staticmethod
    def _range(days: list[date], date_from: date | None, date_to: date | None) -> tuple[date, date]:
        if not days:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pliki urządzeń nie zawierają danych.")
        date_from, date_to = date_from or days[0], date_to or days[-1]
        if date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Data początkowa nie może być późniejsza niż data końcowa.",
            )
        if date_from < days[0] or date_to > days[-1]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Zakres musi mieścić się w okresie dostępnych danych ({days[0]:%d.%m.%Y} – {days[-1]:%d.%m.%Y}).",
            )
        return date_from, date_to

    def _tariff(self, user_id: UUID, requested: str | None, slot_prices: dict) -> DeviceUsageTariff:
        names = {name.lower(): name for name in slot_prices}
        if requested is not None:
            if requested.lower() not in names:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Nieznana taryfa {requested}. Dostępne: {', '.join(sorted(slot_prices))}.",
                )
            return DeviceUsageTariff(name=names[requested.lower()], source="query")

        profile_type, profile_tariff = self.user_service.profile_tariff(user_id)
        if profile_tariff is not None and profile_tariff.name.lower() in names:
            return DeviceUsageTariff(name=names[profile_tariff.name.lower()], source="profile")
        note = (
            f"Taryfa {profile_type} z profilu nie ma cennika dla tych danych, więc koszty są w taryfie G11."
            if profile_type
            else "Profil nie wskazuje taryfy, więc koszty są w taryfie G11."
        )
        if DEFAULT_TARIFF.lower() not in names:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Brak cennika taryfy G11 dla tych danych.")
        return DeviceUsageTariff(name=names[DEFAULT_TARIFF.lower()], source="default", note=note)

    @staticmethod
    def _price_lookup(prices: dict):
        """Cena kwadransu (PLN/kWh) z cennika zapisanego przy imporcie; None, gdy jej brak."""
        by_slot, by_day = prices.get("prices"), prices.get("prices_by_day")

        def price(slot_start: datetime) -> float | None:
            day, slot = _local_slot(slot_start)
            if by_slot is not None:
                return by_slot[slot]
            day_prices = (by_day or {}).get(day)
            return day_prices[slot] if day_prices else None

        return price

    @staticmethod
    def _matches(instance, category: str | None, device_type: str | None, flexible_only: bool = False) -> bool:
        return (
            (category is None or instance.device_category == category)
            and (device_type is None or instance.device_type == device_type)
            and (not flexible_only or instance.flexibility_mode in FLEXIBLE_MODES)
        )

    @staticmethod
    def _group_key(instance, group_by: DeviceUsageGroupBy) -> str:
        if group_by == DeviceUsageGroupBy.CATEGORY:
            return instance.device_category
        if group_by == DeviceUsageGroupBy.TYPE:
            return instance.device_type
        return instance.source_device_id

    @staticmethod
    def _group(key: str, accumulator: _Accumulator, devices: list, group_by: DeviceUsageGroupBy) -> DeviceUsageGroup:
        categories = {instance.device_category for instance, _ in devices}
        types = {(instance.device_type, label) for instance, label in devices}
        device_type, type_label = next(iter(types)) if len(types) == 1 else (None, None)
        instance = devices[0][0] if group_by == DeviceUsageGroupBy.INSTANCE else None
        label = {
            DeviceUsageGroupBy.CATEGORY: key,
            DeviceUsageGroupBy.TYPE: type_label or key,
            DeviceUsageGroupBy.INSTANCE: instance.name if instance else key,
        }[group_by]
        return DeviceUsageGroup(
            key=key,
            label=label,
            category=next(iter(categories)) if len(categories) == 1 else None,
            device_type=device_type,
            device_type_label=type_label,
            device_id=instance.source_device_id if instance else None,
            device_name=instance.name if instance else None,
            devices_count=len(devices),
            flexible_devices_count=sum(instance.flexibility_mode in FLEXIBLE_MODES for instance, _ in devices),
            flexibility_mode=instance.flexibility_mode if instance else None,
            **accumulator.series(),
        )

    def _rest_of_house(
        self, meter, user_id, covering, device_net, start, end, date_from, date_to, axis, price
    ) -> RestOfHouse:
        """Reszta domu = licznik − urządzenia w każdym kwadransie dni, które mają oba źródła.

        Oba źródła liczone są jako saldo z siecią: licznik (pobór − oddanie) i urządzenia
        (zużycie − produkcja PV), więc wynik jest poprawny także dla domu z PV. Kwadrans, w którym
        urządzenia przekraczają licznik, ma resztę 0, a jego dzień trafia do exceeded_days.
        """
        meter_files = self._meter_files(meter, user_id)
        file_ids = [energy_file.id for energy_file in meter_files]
        readings = self.reading_repository.merged_for_files(
            file_ids, start.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None), end.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)
        )
        meter_net = {
            (measured_at.date().isoformat(), measured_at.hour * 4 + measured_at.minute // 15): used - exported
            for measured_at, used, exported in readings
        }
        device_days = {day for day, _ in covering}
        common_days = sorted({day for day, _ in meter_net} & device_days)

        rest = _Accumulator(len(axis.starts))
        balance_by_day, meter_by_day = defaultdict(float), defaultdict(float)
        for (day, slot), meter_kwh in meter_net.items():
            if day not in common_days:
                continue
            difference = meter_kwh - device_net.get((day, slot), 0.0)
            balance_by_day[day] += difference
            meter_by_day[day] += abs(meter_kwh)
            # Czas lokalny z odczytu; powtórzoną godzinę przy zmianie czasu przypisujemy do pierwszego wystąpienia.
            slot_start = datetime.combine(date.fromisoformat(day), time(), LOCAL_TIMEZONE) + slot * SLOT
            rest.add(axis.position(slot_start.astimezone(timezone.utc)), max(difference, 0.0), price(slot_start))

        return RestOfHouse(
            meter_file_ids=file_ids,
            common_days=[date.fromisoformat(day) for day in common_days],
            exceeded_days=[
                date.fromisoformat(day)
                for day in common_days
                if -balance_by_day[day] > max(EXCEEDED_TOLERANCE_MIN_KWH, EXCEEDED_TOLERANCE_SHARE * meter_by_day[day])
            ],
            **rest.series(),
        )

    def _meter_files(self, meter: str, user_id: UUID) -> list[EnergyDataFile]:
        if meter == ALL_FILES_SOURCE_ID:
            files = self.file_repository.list_completed_by_user_id(user_id, EnergyDataFile.SOURCE_METER)
            if not files:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nie masz poprawnie zaimportowanych plików z licznika.")
            return files
        energy_file = self._own_file(meter, user_id)
        if energy_file.source_type != EnergyDataFile.SOURCE_METER or energy_file.status != EnergyDataFile.STATUS_COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Parametr meter musi wskazywać poprawnie zaimportowany plik z licznika albo „all”.",
            )
        return [energy_file]


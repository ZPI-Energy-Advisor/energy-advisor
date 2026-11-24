from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import numpy as np
from fastapi import HTTPException, status

from app.models.DeviceInstance import DeviceInstance
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.device_repository import DeviceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.repositories.simulation_repository import SimulationRepository
from app.schemas.device_usage import (
    CostBreakdown,
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
from app.services.device_series import DeviceSeries, series_cache, source_key
from app.services.quarter_prices import KwhPrice
from app.services.tariff_costs import PartsTotal, PricingProfile, TariffCostService, TariffOption


SLOT = timedelta(minutes=15)
# Urządzenia, których pracę można przenieść na inne godziny (pralka, zmywarka, pompa ciepła, ładowarka EV).
FLEXIBLE_MODES = (DeviceInstance.SHIFTABLE, DeviceInstance.INTERRUPTIBLE)
EXCEEDED_TOLERANCE_SHARE = 0.01
EXCEEDED_TOLERANCE_MIN_KWH = 0.05
ZERO_KWH = Decimal(0)


@dataclass
class _Source:
    """Pliki urządzeń, z których liczymy dane, i ich zapisane wyniki importu."""

    source_id: str
    files: list[EnergyDataFile]
    results: list[dict]
    current_only: bool


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), LOCAL_TIMEZONE).astimezone(timezone.utc)


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
        self._index = None

    @property
    def index(self) -> dict:
        # Potrzebny tylko „Reszcie domu” (pozycja po czasie odczytu), więc budujemy go dopiero wtedy.
        if self._index is None:
            self._index = {self._key(moment): position for position, moment in enumerate(self.starts)}
        return self._index

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
    def __init__(self, size: int, parts: PartsTotal | None = None):
        self.kwh = [0.0] * size
        self.cost = [0.0] * size
        self.parts = parts

    @classmethod
    def of(cls, kwh: np.ndarray, cost: np.ndarray) -> "_Accumulator":
        """Gotowe sumy okresów (z tablic), do tego samego formatu serii co przy dodawaniu kwadransów."""
        accumulator = cls(0)
        accumulator.kwh, accumulator.cost = kwh.tolist(), cost.tolist()
        return accumulator

    def add(self, position: int, kwh: float, price: KwhPrice | None) -> None:
        self.kwh[position] += kwh
        if price is not None:
            self.cost[position] += kwh * float(price.gross)
            if self.parts is not None and kwh > 0:
                self.parts.add(Decimal(str(kwh)), price)

    def series(self) -> dict:
        # Większość okresów to zera (urządzenie nie pracuje): przepisujemy je bez round(), wynik ten sam.
        kwh = [round(value, 6) if value else value for value in self.kwh]
        cost = [round(value, 4) if value else value for value in self.cost]
        return {"kwh": kwh, "cost_pln": cost, "total_kwh": round(sum(self.kwh), 4), "total_cost_pln": round(sum(self.cost), 2)}


class _RangeUsage:
    """Wiersze serii z kwadransów zakresu [start, end): kwadrans, urządzenie i kWh, w kolejności serii."""

    def __init__(self, series: DeviceSeries, start: datetime, end: datetime):
        self.slots = series.slots_between(start, end)
        rows = self.slots[series.row_slot]
        self.rows = np.flatnonzero(rows)
        self.row_slot = series.row_slot[rows]
        self.row_device = series.row_device[rows]
        self.kwh = series.kwh[rows]
        self.present_devices = np.unique(self.row_device)

    def local_net(self, series: DeviceSeries) -> dict[tuple[str, int], float]:
        """Saldo urządzeń (zużycie − produkcja PV) w kwadransie doby lokalnej, do „Reszty domu”.
        Powtórzona godzina przy zmianie czasu trafia do jednego kwadransu lokalnego."""
        net = np.bincount(self.row_slot, weights=self.kwh, minlength=len(series.slot_seconds))
        by_local: dict[tuple[str, int], float] = defaultdict(float)
        for slot in np.unique(self.row_slot).tolist():
            by_local[(series.slot_day[slot], int(series.slot_quarter[slot]))] += float(net[slot])
        return by_local


class DeviceUsageService:
    """Zużycie i koszt urządzeń w podziale na kategorie, typy albo pojedyncze urządzenia (ZP-81).

    Koszt kwadransu to jego zużycie razy pełna cena brutto tego kwadransu (energia, dystrybucja, opłaty za kWh
    i VAT) w wybranej taryfie operatora z profilu, liczona z cennika przy odczycie, tak jak na Dashboardzie.
    """

    def __init__(
        self,
        file_repository: EnergyDataFileRepository,
        simulation_repository: SimulationRepository,
        device_repository: DeviceRepository,
        reading_repository: EnergyReadingRepository,
        tariff_costs: TariffCostService,
    ):
        self.file_repository = file_repository
        self.simulation_repository = simulation_repository
        self.device_repository = device_repository
        self.reading_repository = reading_repository
        self.tariff_costs = tariff_costs

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

        profile = self.tariff_costs.profile(user_id)
        option, tariff_info = self._tariff(profile, tariff, self.tariff_costs.options(profile.operator, date_from, date_to))
        price = self._price_lookup(option, start, end, profile)
        parts = PartsTotal()
        axis = _Axis(date_from, date_to, resolution)

        series = self._series(source, user_id, file_ids)
        usage = _RangeUsage(series, start, end)
        devices = self._devices(series, usage.present_devices)
        matched_devices = np.zeros(len(series.device_ids), dtype=bool)
        for index, (instance, _) in devices.items():
            matched_devices[index] = self._matches(instance, category, device_type, flexible_only)
        matched = matched_devices[usage.row_device]
        positions = self._positions(series, axis, start, date_from)[usage.row_slot]
        size = len(axis.starts)

        production = _Accumulator(size)
        produced = matched & (usage.kwh < 0)
        production.kwh = np.bincount(positions[produced], weights=-usage.kwh[produced], minlength=size).tolist()

        group_keys: dict[str, int] = {}
        device_group = np.full(len(series.device_ids), -1, dtype=np.int64)
        for index, (instance, _) in devices.items():
            if matched_devices[index]:
                device_group[index] = group_keys.setdefault(self._group_key(instance, group_by), len(group_keys))
        used = matched & (usage.kwh >= 0)
        cells = device_group[usage.row_device[used]] * size + positions[used]
        used_kwh = usage.kwh[used]
        cells_count = len(group_keys) * size
        kwh_grid = np.bincount(cells, weights=used_kwh, minlength=cells_count).reshape(len(group_keys), size)
        slot_prices, gross = self._slot_prices(series, usage.slots, price)
        used_gross = gross[usage.row_slot[used]]
        priced = ~np.isnan(used_gross)
        cost_grid = np.bincount(
            cells[priced], weights=used_kwh[priced] * used_gross[priced], minlength=cells_count
        ).reshape(len(group_keys), size)
        missing_price_slots = int(np.count_nonzero(~priced & (used_kwh > 0)))
        # Części rachunku są liniowe względem kWh, więc dodajemy cenę raz na kwadrans, ale kWh sumujemy dokładnie
        # (Decimal każdego wiersza, policzony raz w serii), żeby rozbicie wyszło co do grosza jak przy wierszach.
        billed = priced & (used_kwh > 0)
        slot_kwh: dict[int, Decimal] = {}
        decimals = series.kwh_decimal
        for row, slot in zip(usage.rows[used][billed].tolist(), usage.row_slot[used][billed].tolist()):
            slot_kwh[slot] = slot_kwh.get(slot, ZERO_KWH) + decimals[row]
        for slot, kwh in slot_kwh.items():
            parts.add(kwh, slot_prices[slot])

        members: dict[int, set[int]] = defaultdict(set)
        for group, device in set(zip(device_group[usage.row_device[used]].tolist(), usage.row_device[used].tolist())):
            members[group].add(device)
        group_out = sorted(
            (
                self._group(
                    key, _Accumulator.of(kwh_grid[group], cost_grid[group]),
                    [devices[device] for device in members[group]], group_by,
                )
                for key, group in group_keys.items()
                if members[group]
            ),
            key=lambda group: (-group.total_kwh, group.label),
        )
        device_net = usage.local_net(series) if meter is not None else {}
        rest = None
        if meter is not None:
            rest = self._rest_of_house(
                meter, user_id, covering, device_net, start, end, date_from, date_to, axis, price, parts
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
            cost_breakdown=CostBreakdown(**parts.as_dict()),
            missing_price_slots=missing_price_slots,
        )

    def _series(self, source: _Source, user_id: UUID, file_ids: list[UUID]) -> DeviceSeries:
        """Seria urządzeń źródła z pamięci procesu albo, przy pierwszym zapytaniu, z bazy (ZP-147)."""
        key = source_key(source.files, source.current_only)
        series = series_cache.get(key)
        if series is None:
            series = DeviceSeries.from_rows(
                self.device_repository.slot_usage_series(file_ids, current_only=source.current_only)
            )
            series_cache.put(key, user_id, series)
        return series

    def _devices(self, series: DeviceSeries, indexes: np.ndarray) -> dict[int, tuple[DeviceInstance, str]]:
        """Urządzenia z wierszy zakresu i etykiety ich typów; opisy czytamy z bazy przy każdym zapytaniu,
        bo zmieniają się niezależnie od plików (np. tryb pracy urządzenia)."""
        position = {series.device_ids[index]: index for index in indexes.tolist()}
        return {
            position[instance.id]: (instance, type_label)
            for instance, type_label in self.device_repository.instances_with_type_labels(list(position))
        }

    @staticmethod
    def _positions(series: DeviceSeries, axis: _Axis, start: datetime, date_from: date) -> np.ndarray:
        """Okres osi wykresu dla każdego kwadransu serii (poza zakresem wartości są bez znaczenia)."""
        if axis.resolution == DeviceUsageResolution.DAY:
            return series.slot_ordinal - date_from.toordinal()
        step = int(SLOT.total_seconds()) if axis.resolution == DeviceUsageResolution.QUARTER else 3600
        # Polska strefa ma przesunięcie w pełnych godzinach, więc godziny lokalne i UTC się pokrywają.
        return (series.slot_seconds - int(start.timestamp())) // step

    @staticmethod
    def _slot_prices(series: DeviceSeries, slots: np.ndarray, price) -> tuple[list, np.ndarray]:
        """Cena każdego kwadransu zakresu (KwhPrice albo None) i jej kwota brutto jako float (NaN bez ceny)."""
        prices: list[KwhPrice | None] = [None] * len(series.slot_seconds)
        gross = np.full(len(series.slot_seconds), np.nan)
        for slot in np.flatnonzero(slots).tolist():
            slot_price = price(series.slot_datetime(slot))
            if slot_price is not None:
                prices[slot] = slot_price
                gross[slot] = float(slot_price.gross)
        return prices, gross

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

    @staticmethod
    def _tariff(
        profile: PricingProfile, requested: str | None, options: list[TariffOption]
    ) -> tuple[TariffOption, DeviceUsageTariff]:
        operator = profile.operator.value
        if requested is not None:
            option = next((item for item in options if item.key.lower() == requested.lower()), None)
            if option is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Nieznana taryfa {requested} u operatora {operator}. "
                    f"Dostępne: {', '.join(item.key for item in options) or 'brak'}.",
                )
            return option, DeviceUsageTariff(key=option.key, label=option.label, operator=operator, source="query")

        option, note = TariffCostService.select(profile, options)
        if option is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=note)
        from_profile = profile.from_profile and option.key == profile.key
        if not profile.from_profile:
            note = f"Profil nie wskazuje taryfy, więc koszty są w taryfie {option.label} operatora {operator}."
        return option, DeviceUsageTariff(
            key=option.key, label=option.label, operator=operator,
            source="profile" if from_profile else "default", note=note,
        )

    def _price_lookup(self, option: TariffOption, start: datetime, end: datetime, profile: PricingProfile):
        """Cena kwadransu z rozbiciem z cennika; None, gdy jej brak (np. brak ceny RCE)."""
        try:
            prices = self.tariff_costs.prices(option, start, end, profile).prices
        except (ValueError, LookupError) as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

        def price(slot_start: datetime) -> KwhPrice | None:
            return prices.get(slot_start.astimezone(timezone.utc))

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
        self, meter, user_id, covering, device_net, start, end, date_from, date_to, axis, price, parts=None
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

        rest = _Accumulator(len(axis.starts), parts)
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


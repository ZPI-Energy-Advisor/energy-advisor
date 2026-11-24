"""ZP-147: tablicowe liczenie zużycia urządzeń i pamięć serii źródła.

Nowe liczenie musi dawać dokładnie te same kWh i kwoty co dawna pętla po wierszach (`_legacy_usage` poniżej to
jej kopia sprzed zmiany), także z PV, „Resztą domu”, filtrami i dobą ze zmianą czasu.
"""
import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

import pytest

from app.database import SessionLocal
from app.models.User import User
from app.repositories.device_repository import DeviceRepository
from app.repositories.dynamic_price_repository import DynamicPriceRepository
from app.repositories.energy_data_file_repository import EnergyDataFileRepository
from app.repositories.energy_reading_repository import EnergyReadingRepository
from app.repositories.simulation_repository import SimulationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.device_usage import (
    CostBreakdown, DeviceUsageGroupBy, DeviceUsageResolution, DeviceUsageResponse, KwhSeries,
)
from app.services import device_series
from app.services.calculation_service import CalculationService
from app.services.device_usage_service import DeviceUsageService, _Accumulator, _Axis, _local_midnight
from app.services.pv_service import DynamicMarketPriceResolver
from app.services.tariff_costs import PartsTotal, TariffCostService
from app.parsers.devices import LOCAL_TIMEZONE
from app.schemas.other import TariffTypeEnum
from tariff_helpers import TEST_YEARS, FlatTariffRepository, flat_definition, period
from timing import TIME_LIMIT_SCALE
from test_device_usage import (
    BACKEND_DIR, DEVICES_DEMO, DEVICES_FROM_METER_DEMO, METER_DEMO, _create_document_file, _create_meter_file,
)
from test_energy_files import T0, T1, _create_devices_file, _create_user, _delete, _devices_document


# Cennik w pamięci z ceną zależną od pory dnia i VAT 23%, żeby porównanie obejmowało różne ceny kwadransów
# i rozbicie kosztu na części (przy jednej cenie bez VAT koszt równałby się kWh).
TARIFFS = FlatTariffRepository(
    [
        flat_definition(energy=("0.62",), network=("0.35",)),
        flat_definition(TariffTypeEnum.G12, energy=("0.71", "0.43"), network=("0.41", "0.12")),
    ],
    [period(quality="0.0313", renewable="0.0073", cogeneration="0.003", excise="0.005", vat="0.23", valid=TEST_YEARS)],
)


@pytest.fixture
def db():
    """Jak w test_device_usage: _create_user zapisuje id użytkowników do usunięcia po teście."""
    session = SessionLocal()
    session.created_users = []
    yield session
    session.rollback()
    for user_id in session.created_users:
        session.query(User).filter(User.id == user_id).delete()
    session.commit()
    session.close()


@pytest.fixture(scope="module")
def yearly_document(tmp_path_factory):
    path = tmp_path_factory.mktemp("rok") / "rok.json"
    subprocess.run(
        [sys.executable, str(BACKEND_DIR / "scripts" / "generate_devices_file.py"),
         "--start", "2025-01-01", "--days", "365", "--seed", "3", "--out", str(path)],
        check=True, capture_output=True,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _service(db):
    return DeviceUsageService(
        EnergyDataFileRepository(db),
        SimulationRepository(db),
        DeviceRepository(db),
        EnergyReadingRepository(db),
        TariffCostService(TARIFFS, UserRepository(db), DynamicMarketPriceResolver(DynamicPriceRepository(db))),
    )


def _local_slot(moment):
    local = moment.astimezone(LOCAL_TIMEZONE)
    return local.date().isoformat(), local.hour * 4 + local.minute // 15


def _legacy_usage(
    service, source_id, user_id, *, group_by=DeviceUsageGroupBy.CATEGORY, resolution=DeviceUsageResolution.HOUR,
    date_from=None, date_to=None, tariff=None, category=None, device_type=None, flexible_only=False, meter=None,
):
    """Dawne DeviceUsageService.get_usage: pętla po wierszach z bazy dla zakresu (kopia sprzed ZP-147)."""
    source = service._source(source_id, user_id)
    file_ids = [energy_file.id for energy_file in source.files]
    covering = CalculationService.device_coverage([results["usage_15min"] for results in source.results])
    covered_days = sorted({date.fromisoformat(day) for day, _ in covering})
    date_from, date_to = service._range(covered_days, date_from, date_to)
    start, end = _local_midnight(date_from), _local_midnight(date_to + timedelta(days=1))

    profile = service.tariff_costs.profile(user_id)
    option, tariff_info = service._tariff(profile, tariff, service.tariff_costs.options(profile.operator, date_from, date_to))
    price = service._price_lookup(option, start, end, profile)
    parts = PartsTotal()

    rows = service.device_repository.slot_usage(file_ids, start, end, current_only=source.current_only)
    devices = {
        instance.id: (instance, type_label)
        for instance, type_label in service.device_repository.instances_with_type_labels(list({row[1] for row in rows}))
    }

    axis = _Axis(date_from, date_to, resolution)
    groups, members = defaultdict(lambda: _Accumulator(len(axis.starts), parts)), defaultdict(set)
    production = _Accumulator(len(axis.starts))
    device_net = defaultdict(float)
    missing_price_slots = 0
    for slot_start, instance_id, kwh in rows:
        instance, _ = devices[instance_id]
        device_net[_local_slot(slot_start)] += kwh
        if not service._matches(instance, category, device_type, flexible_only):
            continue
        position = axis.position(slot_start)
        if kwh < 0:
            production.add(position, -kwh, None)
            continue
        slot_price = price(slot_start)
        missing_price_slots += slot_price is None and kwh > 0
        key = service._group_key(instance, group_by)
        groups[key].add(position, kwh, slot_price)
        members[key].add(instance_id)

    group_out = sorted(
        (service._group(key, groups[key], [devices[device_id] for device_id in members[key]], group_by) for key in groups),
        key=lambda group: (-group.total_kwh, group.label),
    )
    rest = None
    if meter is not None:
        rest = service._rest_of_house(meter, user_id, covering, device_net, start, end, date_from, date_to, axis, price, parts)
    has_production = any(production.kwh)
    total_kwh = sum(group.total_kwh for group in group_out) + (rest.total_kwh if rest else 0.0)
    total_cost = sum(group.total_cost_pln for group in group_out) + (rest.total_cost_pln if rest else 0.0)
    return DeviceUsageResponse(
        source_id=source.source_id, date_from=date_from, date_to=date_to, group_by=group_by, resolution=resolution,
        tariff=tariff_info, periods=axis.periods(), groups=group_out,
        production=KwhSeries(**{key: production.series()[key] for key in ("kwh", "total_kwh")}) if has_production else None,
        rest_of_house=rest, total_kwh=round(total_kwh, 4), total_cost_pln=round(total_cost, 2),
        cost_breakdown=CostBreakdown(**parts.as_dict()), missing_price_slots=missing_price_slots,
    )


CASES = [
    {},
    {"group_by": DeviceUsageGroupBy.TYPE, "resolution": DeviceUsageResolution.DAY},
    {"group_by": DeviceUsageGroupBy.INSTANCE, "resolution": DeviceUsageResolution.QUARTER},
    {"group_by": DeviceUsageGroupBy.TYPE, "category": "AGD"},
    {"group_by": DeviceUsageGroupBy.INSTANCE, "device_type": "ev_charger", "resolution": DeviceUsageResolution.QUARTER},
    {"flexible_only": True, "resolution": DeviceUsageResolution.DAY},
    # Tydzień ze zmianą czasu (25.10.2026: doba 100 kwadransów).
    {"group_by": DeviceUsageGroupBy.INSTANCE, "resolution": DeviceUsageResolution.QUARTER,
     "date_from": date(2026, 10, 23), "date_to": date(2026, 10, 27)},
    {"resolution": DeviceUsageResolution.HOUR, "date_from": date(2026, 10, 5), "date_to": date(2026, 10, 5)},
    {"meter": "all"},
    {"meter": "all", "group_by": DeviceUsageGroupBy.INSTANCE, "resolution": DeviceUsageResolution.QUARTER},
    {"meter": "all", "category": "AGD", "resolution": DeviceUsageResolution.DAY},
    {"tariff": "G12", "group_by": DeviceUsageGroupBy.TYPE, "resolution": DeviceUsageResolution.QUARTER},
    {"tariff": "G12", "meter": "all", "group_by": DeviceUsageGroupBy.INSTANCE},
]


@pytest.fixture
def house(db):
    """Dom z PV (plik demo) i nowszy plik urządzeń częściowo go przykrywający, plus licznik do „Reszty domu”."""
    user = _create_user(db)
    with_pv = _create_document_file(db, user, DEVICES_DEMO, name="pv.json", uploaded_at=T0)
    newer = _create_document_file(db, user, DEVICES_FROM_METER_DEMO, name="dom.json", uploaded_at=T1)
    _create_meter_file(db, user, METER_DEMO, name="licznik.csv", uploaded_at=T0)
    return user, with_pv, newer


def test_new_aggregation_gives_exactly_the_same_kwh_and_amounts_as_row_loop(db, house):
    # Wszystkie przypadki na jednym domu (założenie domu z trzema plikami jest najdroższą częścią testu).
    user, with_pv, _ = house
    service = _service(db)
    different = []
    for source_id in ("all-devices", str(with_pv.id)):
        for index, case in enumerate(CASES):
            expected = _legacy_usage(service, source_id, user.id, **case).model_dump()
            actual = service.get_usage(source_id, user.id, **case).model_dump()
            if actual != expected:
                different.append((source_id, index, case))

    assert different == []
    assert service.get_usage(str(with_pv.id), user.id).production.total_kwh > 0


def test_series_is_read_from_the_database_once_per_source(db, house, monkeypatch):
    user, with_pv, _ = house
    service = _service(db)
    calls = []
    original = DeviceRepository.slot_usage_series
    monkeypatch.setattr(
        DeviceRepository, "slot_usage_series", lambda self, *args, **kwargs: calls.append(args) or original(self, *args, **kwargs)
    )

    for case in CASES[:4]:
        service.get_usage("all-devices", user.id, **case)
    service.get_usage(str(with_pv.id), user.id)

    # Jedno czytanie dla „Wszystkich plików urządzeń” i jedno dla pojedynczego pliku, mimo pięciu zapytań.
    assert len(calls) == 2


def test_new_or_deleted_file_reads_the_series_again(db, house, monkeypatch):
    user, with_pv, newer = house
    service = _service(db)
    before = service.get_usage("all-devices", user.id).model_dump()
    calls = []
    original = DeviceRepository.slot_usage_series
    monkeypatch.setattr(
        DeviceRepository, "slot_usage_series", lambda self, *args, **kwargs: calls.append(args) or original(self, *args, **kwargs)
    )

    assert _delete(user, newer.id).status_code == 204
    db.expire_all()
    after_delete = service.get_usage("all-devices", user.id).model_dump()
    _create_devices_file(db, user, _october_washer(), name="pralka.json", uploaded_at=T1 + timedelta(days=1))
    service.get_usage("all-devices", user.id)

    assert len(calls) == 2
    assert after_delete["total_kwh"] != before["total_kwh"]


def test_forget_user_drops_only_that_users_series(db, house):
    user, _, _ = house
    other = _create_user(db)
    _create_document_file(db, other, DEVICES_DEMO, name="pv.json", uploaded_at=T0)
    service = _service(db)
    service.get_usage("all-devices", user.id)
    service.get_usage("all-devices", other.id)
    assert len(device_series.series_cache) == 2

    device_series.forget_user_series(user.id)

    assert len(device_series.series_cache) == 1


def _october_washer():
    """Nowy, mały plik urządzeń w październiku (strefa w pomocniku jest zimowa, w październiku obowiązuje letnia)."""
    document = _devices_document(
        "2026-10-10T00:00:00", "2026-10-11T00:00:00", {"dev_new": [("2026-10-10T10:00:00", "2026-10-10T11:00:00", 1.2)]}
    )
    return json.loads(json.dumps(document).replace("+01:00", "+02:00"))


@pytest.mark.perf
def test_year_of_devices_changes_view_quickly_after_first_read(db, yearly_document):
    user = _create_user(db)
    _create_devices_file(db, user, yearly_document, name="rok.json", uploaded_at=T0)
    service = _service(db)

    started = time.perf_counter()
    service.get_usage("all-devices", user.id)
    first = time.perf_counter() - started
    timings = {}
    for name, case in {
        "kategorie, godzinowo": {},
        "typy, dziennie": {"group_by": DeviceUsageGroupBy.TYPE, "resolution": DeviceUsageResolution.DAY},
        "urządzenia, 15 min": {"group_by": DeviceUsageGroupBy.INSTANCE, "resolution": DeviceUsageResolution.QUARTER},
        "miesiąc, 15 min": {"resolution": DeviceUsageResolution.QUARTER, "date_from": date(2025, 3, 1), "date_to": date(2025, 3, 31)},
    }.items():
        started = time.perf_counter()
        service.get_usage("all-devices", user.id, **case)
        timings[name] = time.perf_counter() - started

    assert first < 3.0 * TIME_LIMIT_SCALE, first
    # Kolejne kliknięcia korzystają z serii w pamięci (dawniej 2,5–3,5 s każde).
    assert max(timings.values()) < 0.5 * TIME_LIMIT_SCALE, timings


# Usuwanie pliku przez API (test_new_or_deleted_file_reads_the_series_again) liczy koszty na cenniku w pamięci.
pytestmark = pytest.mark.usefixtures("flat_tariffs")

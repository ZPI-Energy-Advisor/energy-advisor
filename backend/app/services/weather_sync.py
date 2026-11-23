import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Callable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.EnergyDataFile import EnergyDataFile
from app.models.UserProfile import UserProfile as UserProfileRow
from app.providers.weather import Plane
from app.repositories.user_repository import UserRepository
from app.repositories.weather_repository import WeatherRepository
from app.services.user_service import UserService
from app.services.weather_service import Cell, WeatherService, planes_of

logger = logging.getLogger(__name__)


@dataclass
class Home:
    user_id: UUID
    cell: Cell
    planes: list[Plane]
    history_days: set[date] = field(default_factory=set)


@dataclass
class SyncResult:
    cells: int = 0
    stored: int = 0
    failed: int = 0


def _file_days(db: Session, user_id: UUID | None) -> dict[UUID, set[date]]:
    query = db.query(EnergyDataFile.user_id, EnergyDataFile.data_start, EnergyDataFile.data_end).filter(
        EnergyDataFile.status == EnergyDataFile.STATUS_COMPLETED,
        EnergyDataFile.data_start.isnot(None),
        EnergyDataFile.data_end.isnot(None),
    )
    if user_id is not None:
        query = query.filter(EnergyDataFile.user_id == user_id)
    days: dict[UUID, set[date]] = defaultdict(set)
    for owner, start, end in query.all():
        days[owner].update(start + timedelta(days=offset) for offset in range((end - start).days + 1))
    return days


def homes(db: Session, user_id: UUID | None = None) -> list[Home]:
    query = db.query(UserProfileRow.user_id)
    if user_id is not None:
        query = query.filter(UserProfileRow.user_id == user_id)
    file_days = _file_days(db, user_id)
    users = UserService(UserRepository(db))
    found = []
    for (owner,) in query.all():
        try:
            profile = users.get_profile(SimpleNamespace(id=owner))
        except HTTPException:
            continue
        except Exception:
            db.rollback()
            logger.exception("Pomijam profil %s przy pobieraniu pogody", owner)
            continue
        planes = planes_of(profile)
        days = file_days.get(owner, set())
        if profile.base_info.location is None or not (planes or days):
            continue
        found.append(Home(owner, Cell.of(profile.base_info.location), planes, days))
    return found


def _by_cell(found: list[Home]) -> dict[Cell, tuple[list[Plane], set[date]]]:
    planes: dict[Cell, set[Plane]] = defaultdict(set)
    days: dict[Cell, set[date]] = defaultdict(set)
    for home in found:
        planes[home.cell].update(home.planes)
        days[home.cell].update(home.history_days)
    return {cell: (sorted(planes[cell]), days[cell]) for cell in planes}


def _each_cell(db: Session, cells: dict, job: Callable[[Cell, list[Plane], set[date]], int], name: str) -> SyncResult:
    result = SyncResult()
    for cell, (planes, days) in cells.items():
        result.cells += 1
        try:
            result.stored += job(cell, planes, days)
        except Exception as error:
            db.rollback()
            result.failed += 1
            logger.warning("%s dla komórki %s, %s nieudana: %s", name, cell.latitude, cell.longitude, error)
    return result


def refresh_forecasts(db: Session, service: WeatherService | None = None, user_id: UUID | None = None) -> SyncResult:
    service = service or WeatherService(WeatherRepository(db))
    return _each_cell(
        db, _by_cell(homes(db, user_id)), lambda cell, planes, _: service.refresh_forecast(cell, planes), "Prognoza"
    )


def ensure_forecasts(db: Session, service: WeatherService | None = None, user_id: UUID | None = None) -> SyncResult:
    service = service or WeatherService(WeatherRepository(db))
    return _each_cell(
        db, _by_cell(homes(db, user_id)), lambda cell, planes, _: service.ensure_forecast(cell, planes), "Prognoza"
    )


def sync_history(db: Session, service: WeatherService | None = None, user_id: UUID | None = None) -> SyncResult:
    service = service or WeatherService(WeatherRepository(db))
    cells = {cell: value for cell, value in _by_cell(homes(db, user_id)).items() if value[1]}
    return _each_cell(db, cells, lambda cell, planes, days: service.ensure_history(cell, days, planes), "Historia")


def prune(db: Session, service: WeatherService | None = None) -> SyncResult:
    service = service or WeatherService(WeatherRepository(db))
    return SyncResult(stored=service.prune())


def _in_background(name: str, user_id: UUID, jobs) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        for job in jobs:
            result = job(db, user_id=user_id)
            logger.info("%s: komórki=%d, rekordy=%d, błędy=%d", name, result.cells, result.stored, result.failed)
    except Exception:
        logger.exception("%s zakończone błędem", name)
    finally:
        db.close()


def sync_history_after_upload(user_id: UUID) -> None:
    _in_background("Pogoda po imporcie pliku", user_id, [sync_history])


def sync_after_profile_change(user_id: UUID) -> None:
    _in_background("Pogoda po zmianie profilu", user_id, [ensure_forecasts, sync_history])

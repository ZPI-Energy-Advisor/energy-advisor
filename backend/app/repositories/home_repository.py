from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceAction import DeviceAction
from app.models.DeviceProgram import DeviceProgram
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.models.HomeConnection import HomeConnection
from app.schemas.smart_home import (
    AllowedWindow,
    HomeDeviceProgram,
    HubDevice,
    HubFlexibility,
    HubProgram,
    ReplaySlot,
)



def clock_text(value: time) -> str:
    """Godzina z bazy jako HH:MM (okna z pliku urządzeń; używa też plan na jutro)."""
    return value.strftime("%H:%M")


class HomeRepository:
    """Wiersz home_connection i rejestr urządzeń domu w kształcie PUT /home/devices."""

    def __init__(self, db: Session):
        self.db = db

    def get(self) -> HomeConnection:
        return self.db.get(HomeConnection, HomeConnection.SINGLE_ROW_ID)

    def lock(self) -> HomeConnection:
        """Blokuje wiersz domu do końca transakcji (commit albo rollback).

        Wysyłki rejestru czekają na siebie, więc każda wysyła stan bazy zatwierdzony przed nią,
        a starszy rejestr nigdy nie nadpisze w hubie nowszego.
        """
        return self.db.execute(
            select(HomeConnection)
            .where(HomeConnection.id == HomeConnection.SINGLE_ROW_ID)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()

    def registry(self, user_id: UUID) -> list[HubDevice]:
        """Urządzenia domu użytkownika z programami, w stałej kolejności (od niej zależy skrót rejestru)."""
        instances = self.db.execute(
            select(DeviceInstance)
            .where(DeviceInstance.user_id == user_id)
            .order_by(DeviceInstance.source_device_id)
        ).scalars().all()
        if not instances:
            return []
        programs = defaultdict(list)
        for program in self.db.execute(
            select(DeviceProgram)
            .join(DeviceInstance, DeviceInstance.id == DeviceProgram.device_instance_id)
            .where(DeviceInstance.user_id == user_id)
            .order_by(DeviceProgram.device_instance_id, DeviceProgram.source_program_id)
        ).scalars():
            programs[program.device_instance_id].append(HubProgram(
                program_id=program.source_program_id,
                program_name=program.name,
                duration_min=program.duration_min,
                profile_kwh=list(program.profile_kwh),
            ))
        return [self._hub_device(instance, programs[instance.id]) for instance in instances]

    def device_descriptions(self, user_id: UUID) -> dict[str, dict]:
        """Opis urządzeń do stanu domu (nazwa, typ, kategoria, pomieszczenie, tryb, programy) według device_id.

        `room` to wartość z pliku (None bez pola); domyślne pomieszczenie dopisuje HomeStateService.

        Bez profili programów: stan domu jest odpytywany co kilka sekund, a profile nie są w nim potrzebne.
        """
        devices = self.db.execute(
            select(
                DeviceInstance.id,
                DeviceInstance.source_device_id,
                DeviceInstance.name,
                DeviceInstance.device_type,
                DeviceInstance.device_category,
                DeviceInstance.room,
                DeviceInstance.flexibility_mode,
            ).where(DeviceInstance.user_id == user_id)
        ).all()
        if not devices:
            return {}
        programs = defaultdict(list)
        for program in self.db.execute(
            select(
                DeviceProgram.device_instance_id,
                DeviceProgram.source_program_id,
                DeviceProgram.name,
                DeviceProgram.duration_min,
            )
            .join(DeviceInstance, DeviceInstance.id == DeviceProgram.device_instance_id)
            .where(DeviceInstance.user_id == user_id)
            .order_by(DeviceProgram.device_instance_id, DeviceProgram.source_program_id)
        ):
            programs[program.device_instance_id].append(HomeDeviceProgram(
                program_id=program.source_program_id,
                program_name=program.name,
                duration_min=program.duration_min,
            ))
        return {
            device.source_device_id: {
                "device_type": device.device_type,
                "device_category": device.device_category,
                "device_name": device.name,
                "room": device.room,
                "flexibility_mode": device.flexibility_mode,
                "programs": programs[device.id],
            }
            for device in devices
        }

    def action_slots(
        self, user_id: UUID, device_ids: list[str], start_utc: datetime, end_utc: datetime,
    ) -> list[ReplaySlot]:
        """Kwadranse akcji wskazanych urządzeń w [start_utc, end_utc), np. PV dnia referencyjnego (ZP-113).

        Tylko kwadranse nieprzykryte nowszym plikiem (superseded), jak w danych „Wszystkich plików”,
        więc dwa pliki z tą samą dobą nie odtworzą akcji dwa razy.
        """
        if not device_ids:
            return []
        rows = self.db.execute(
            select(
                DeviceInstance.source_device_id,
                DeviceAction.id,
                DeviceAction.source_action_id,
                DeviceSlotUsage.slot_start,
                DeviceSlotUsage.kwh,
            )
            .join(DeviceAction, DeviceAction.id == DeviceSlotUsage.device_action_id)
            .join(DeviceInstance, DeviceInstance.id == DeviceAction.device_instance_id)
            .where(
                DeviceInstance.user_id == user_id,
                DeviceInstance.source_device_id.in_(device_ids),
                DeviceSlotUsage.superseded.is_(False),
                DeviceSlotUsage.slot_start >= start_utc,
                DeviceSlotUsage.slot_start < end_utc,
            )
            .order_by(DeviceInstance.source_device_id, DeviceSlotUsage.slot_start)
        ).all()
        return [
            ReplaySlot(device_id=device_id, action_id=action_id, ref=ref, slot_start=slot_start, kwh=kwh)
            for device_id, action_id, ref, slot_start, kwh in rows
        ]

    def last_action_starts(
        self, user_id: UUID, device_ids: list[str], before_utc: datetime | None = None,
    ) -> dict[str, datetime]:
        """Start ostatniej akcji z historii każdego z urządzeń przed `before_utc` (bez niego: w ogóle).

        Jak historia planu (`PlanningRepository.device_actions`): liczy się start akcji, a akcje w całości
        przykryte nowszym plikiem pomijamy. Urządzenia bez takiej akcji nie ma w wyniku.
        """
        if not device_ids:
            return {}
        current = (
            select(DeviceSlotUsage.device_action_id)
            .where(DeviceSlotUsage.device_action_id == DeviceAction.id, DeviceSlotUsage.superseded.is_(False))
            .exists()
        )
        conditions = [DeviceInstance.user_id == user_id, DeviceInstance.source_device_id.in_(device_ids), current]
        if before_utc is not None:
            conditions.append(DeviceAction.action_start < before_utc)
        return dict(self.db.execute(
            select(DeviceInstance.source_device_id, func.max(DeviceAction.action_start))
            .join(DeviceInstance, DeviceInstance.id == DeviceAction.device_instance_id)
            .where(*conditions)
            .group_by(DeviceInstance.source_device_id)
        ).all())

    def device_ids_of_types(self, user_id: UUID, device_types: Iterable[str]) -> list[str]:
        return list(self.db.execute(
            select(DeviceInstance.source_device_id)
            .where(DeviceInstance.user_id == user_id, DeviceInstance.device_type.in_(list(device_types)))
            .order_by(DeviceInstance.source_device_id)
        ).scalars())

    def device_info(self, user_id: UUID, device_ids: list[str]) -> dict[str, tuple[str, float | None]]:
        """Typ i moc maksymalna (kW) urządzeń o podanych identyfikatorach z pliku."""
        if not device_ids:
            return {}
        return {
            device_id: (device_type, float(max_power) if max_power is not None else None)
            for device_id, device_type, max_power in self.db.execute(
                select(DeviceInstance.source_device_id, DeviceInstance.device_type, DeviceInstance.max_power_kw)
                .where(DeviceInstance.user_id == user_id, DeviceInstance.source_device_id.in_(device_ids))
            ).all()
        }

    def device_names(self, user_id: UUID) -> dict[str, str]:
        return dict(self.db.execute(
            select(DeviceInstance.source_device_id, DeviceInstance.name).where(DeviceInstance.user_id == user_id)
        ).all())

    def commit(self) -> None:
        self.db.commit()

    @staticmethod
    def _hub_device(instance: DeviceInstance, programs: list[HubProgram]) -> HubDevice:
        window = None
        if instance.allowed_window_from is not None and instance.allowed_window_to is not None:
            window = AllowedWindow(from_=clock_text(instance.allowed_window_from), to=clock_text(instance.allowed_window_to))
        return HubDevice(
            device_id=instance.source_device_id,
            device_name=instance.name,
            device_type=instance.device_type,
            device_category=instance.device_category,
            room=instance.room,
            max_power_kw=instance.max_power_kw,
            flexibility=HubFlexibility(
                mode=instance.flexibility_mode,
                allowed_window=window,
                max_shift_min=instance.max_shift_min,
            ),
            programs=programs,
        )

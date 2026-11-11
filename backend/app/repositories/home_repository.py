from collections import defaultdict
from datetime import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceProgram import DeviceProgram
from app.models.HomeConnection import HomeConnection
from app.schemas.smart_home import AllowedWindow, HomeDeviceProgram, HubDevice, HubFlexibility, HubProgram



def _clock(value: time) -> str:
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
        """Opis urządzeń do stanu domu (typ, kategoria, tryb, programy) według device_id.

        Bez profili programów: stan domu jest odpytywany co kilka sekund, a profile nie są w nim potrzebne.
        """
        devices = self.db.execute(
            select(
                DeviceInstance.id,
                DeviceInstance.source_device_id,
                DeviceInstance.device_type,
                DeviceInstance.device_category,
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
                "flexibility_mode": device.flexibility_mode,
                "programs": programs[device.id],
            }
            for device in devices
        }

    def commit(self) -> None:
        self.db.commit()

    @staticmethod
    def _hub_device(instance: DeviceInstance, programs: list[HubProgram]) -> HubDevice:
        window = None
        if instance.allowed_window_from is not None and instance.allowed_window_to is not None:
            window = AllowedWindow(from_=_clock(instance.allowed_window_from), to=_clock(instance.allowed_window_to))
        return HubDevice(
            device_id=instance.source_device_id,
            device_name=instance.name,
            device_type=instance.device_type,
            device_category=instance.device_category,
            max_power_kw=instance.max_power_kw,
            flexibility=HubFlexibility(
                mode=instance.flexibility_mode,
                allowed_window=window,
                max_shift_min=instance.max_shift_min,
            ),
            programs=programs,
        )

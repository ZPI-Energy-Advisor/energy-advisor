from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceProgram import DeviceProgram
from app.models.PlanningTemplate import PlanningTemplate


FLEXIBLE_MODES = (DeviceInstance.SHIFTABLE, DeviceInstance.INTERRUPTIBLE)
EV_DEVICE_TYPE = "ev_charger"


class PlanningRepository:
    """Urządzenia użytkownika, które da się planować, i jego ustawienia planu na jutro."""

    def __init__(self, db: Session):
        self.db = db

    def flexible_devices(self, user_id: UUID) -> list[tuple[DeviceInstance, list[DeviceProgram]]]:
        """Urządzenia do zaplanowania, po nazwie: shiftable i interruptible z programami oraz ładowarka EV.

        Urządzenie elastyczne bez programów (np. pompa ciepła) pomijamy: samo „pracuje jutro” nie mówi,
        ile energii i jak długo ma pracować.
        """
        devices = self.db.execute(
            select(DeviceInstance)
            .where(DeviceInstance.user_id == user_id, DeviceInstance.flexibility_mode.in_(FLEXIBLE_MODES))
            .order_by(DeviceInstance.name, DeviceInstance.source_device_id)
        ).scalars().all()
        programs = defaultdict(list)
        if devices:
            for program in self.db.execute(
                select(DeviceProgram)
                .where(DeviceProgram.device_instance_id.in_([device.id for device in devices]))
                .order_by(DeviceProgram.device_instance_id, DeviceProgram.source_program_id)
            ).scalars():
                programs[program.device_instance_id].append(program)
        return [
            (device, programs[device.id])
            for device in devices
            if programs[device.id] or device.device_type == EV_DEVICE_TYPE
        ]

    def get_template(self, user_id: UUID) -> PlanningTemplate | None:
        return self.db.get(PlanningTemplate, user_id)

    def save_template(self, user_id: UUID, devices: list[dict]) -> PlanningTemplate:
        template = self.get_template(user_id)
        if template is None:
            template = PlanningTemplate(user_id=user_id, devices=devices)
            self.db.add(template)
        else:
            template.devices = devices
        self.db.commit()
        self.db.refresh(template)
        return template

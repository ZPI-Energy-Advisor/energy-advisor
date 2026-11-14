from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.DeviceAction import DeviceAction
from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.models.DeviceProgram import DeviceProgram
from app.models.PlanningTemplate import PlanningTemplate
from app.models.UserProfile import UserProfile


FLEXIBLE_MODES = (DeviceInstance.SHIFTABLE, DeviceInstance.INTERRUPTIBLE)
EV_DEVICE_TYPE = "ev_charger"
# Planowane automatycznie z historii zużycia, bez programów (ZP-112).
AUTO_DEVICE_TYPES = ("heat_pump", "water_heater")


class PlanningRepository:
    """Urządzenia użytkownika, które da się planować, i jego ustawienia planu na jutro."""

    def __init__(self, db: Session):
        self.db = db

    def flexible_devices(self, user_id: UUID) -> list[tuple[DeviceInstance, list[DeviceProgram]]]:
        """Urządzenia do zaplanowania, po nazwie: shiftable i interruptible z programami, ładowarka EV
        oraz pompa ciepła i bojler (ich energię bierzemy z historii).

        Inne urządzenie elastyczne bez programów pomijamy: samo „pracuje jutro” nie mówi,
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
            if programs[device.id] or device.device_type == EV_DEVICE_TYPE or device.device_type in AUTO_DEVICE_TYPES
        ]

    def device_actions(self, device_instance_ids: list) -> dict:
        """Akcje urządzeń z plików (historia zużycia), po czasie startu: id urządzenia -> lista akcji.

        Bez akcji zastąpionych nowszym plikiem za ten sam okres (te same dni wgrane dwa razy): inaczej
        każdy blok pompy ciepła liczyłby się tyle razy, ile razy wgrano plik.
        """
        current = (
            select(DeviceSlotUsage.device_action_id)
            .where(DeviceSlotUsage.device_action_id == DeviceAction.id, DeviceSlotUsage.superseded.is_(False))
            .exists()
        )
        result = defaultdict(list)
        if device_instance_ids:
            for action in self.db.execute(
                select(DeviceAction)
                .where(DeviceAction.device_instance_id.in_(device_instance_ids), DeviceAction.energy_kwh > 0, current)
                .order_by(DeviceAction.action_start)
            ).scalars():
                result[action.device_instance_id].append(action)
        return result

    def fixed_slot_usage(
        self, user_id: UUID, days: int, extra_instance_ids: list[UUID] | None = None,
    ) -> list[tuple[datetime, float]]:
        """Pobór urządzeń stałych (lodówka, światło, płyta…) w kwadransach z ostatnich `days` dni w plikach:
        (początek kwadransu, kWh), bez produkcji PV i bez kwadransów zastąpionych nowszym plikiem.

        `extra_instance_ids`: urządzenia elastyczne liczone jak stałe, bo plan ich nie układa, a i tak pracują
        (odznaczona pompa ciepła albo bojler)."""
        counted = DeviceInstance.flexibility_mode == DeviceInstance.FIXED
        if extra_instance_ids:
            counted = or_(counted, DeviceInstance.id.in_(extra_instance_ids))
        fixed = (
            select(DeviceSlotUsage.slot_start, DeviceSlotUsage.kwh)
            .join(DeviceAction, DeviceAction.id == DeviceSlotUsage.device_action_id)
            .join(DeviceInstance, DeviceInstance.id == DeviceAction.device_instance_id)
            .where(
                DeviceInstance.user_id == user_id,
                counted,
                DeviceSlotUsage.superseded.is_(False),
                DeviceSlotUsage.kwh > 0,
            )
        )
        latest = self.db.execute(select(func.max(fixed.subquery().c.slot_start))).scalar()
        if latest is None:
            return []
        # Doba więcej, żeby objąć całe doby lokalne; dokładne `days` dni wybiera plan_history.
        since = latest - timedelta(days=days + 1)
        return [tuple(row) for row in self.db.execute(fixed.where(DeviceSlotUsage.slot_start > since)).all()]

    def flat_tariff(self, user_id: UUID) -> bool:
        """Taryfa ze stałą ceną przez całą dobę (G11 bez ceny dynamicznej): przesuwanie nic nie oszczędza."""
        profile = self.db.get(UserProfile, user_id)
        tariff = (profile.consumption_and_tariff or {}) if profile else {}
        dynamic = tariff.get("dynamic_price") or tariff.get("tariff_type") == "dynamic"
        return tariff.get("tariff_type") == "G11" and not dynamic

    def residents(self, user_id: UUID) -> int | None:
        """Liczba osób z profilu (potrzebna bojlerowi); None bez profilu."""
        profile = self.db.get(UserProfile, user_id)
        value = (profile.base_info or {}).get("number_of_residents") if profile else None
        return int(value) if value else None

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

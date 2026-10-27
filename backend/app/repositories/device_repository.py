import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models.DeviceAction import DeviceAction
from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceProgram import DeviceProgram
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.parsers.device_records import ActionRecord, DeviceRecord


SLOT = timedelta(minutes=15)


def _utc(moment: datetime | None) -> datetime | None:
    return moment.astimezone(timezone.utc) if moment is not None else None


class DeviceRepository:
    """Zapis i odczyt urządzeń z pliku urządzeń."""

    def __init__(self, db: Session):
        self.db = db

    def save_for_file(self, *, user_id: UUID, energy_data_file_id: UUID, devices: list[DeviceRecord]) -> None:
        """Dodaje do bieżącej transakcji urządzenia pliku z programami, akcjami i kwadransami.

        Każda tabela trafia do bazy jednym wsadowym INSERT-em, więc czas zapisu zależy od liczby
        tabel, a nie od liczby akcji. Niespójne dane są odrzucane przed pierwszym INSERT-em.
        """
        self._check_slots(devices)
        instance_ids = self._save_instances(user_id, energy_data_file_id, devices)
        program_ids = self._save_programs(devices, instance_ids)
        saved_actions = self._save_actions(devices, instance_ids, program_ids)
        self._save_slots(energy_data_file_id, saved_actions)

    def list_for_file(self, energy_data_file_id: UUID, user_id: UUID) -> list[DeviceInstance]:
        return (
            self.db.query(DeviceInstance)
            .filter(
                DeviceInstance.energy_data_file_id == energy_data_file_id,
                DeviceInstance.user_id == user_id,
            )
            .order_by(DeviceInstance.source_device_id)
            .all()
        )

    @staticmethod
    def _check_slots(devices: list[DeviceRecord]) -> None:
        for device in devices:
            for action in device.actions:
                if _utc(action.start) + len(action.slots_kwh) * SLOT != _utc(action.end):
                    raise ValueError(f"{action.action_id}: liczba kwadransów nie odpowiada czasowi trwania akcji")

    def _save_instances(self, user_id: UUID, energy_data_file_id: UUID, devices: list[DeviceRecord]) -> dict[str, UUID]:
        """Zwraca id urządzeń w bazie według device_id z pliku. Id nadajemy sami, więc nie trzeba RETURNING."""
        instance_ids = {device.device_id: uuid.uuid4() for device in devices}
        self._insert(DeviceInstance, [
            {
                "id": instance_ids[device.device_id],
                "user_id": user_id,
                "energy_data_file_id": energy_data_file_id,
                "source_device_id": device.device_id,
                "name": device.name,
                "device_type": device.device_type,
                "device_category": device.device_category,
                "max_power_kw": device.max_power_kw,
                "flexibility_mode": device.flexibility_mode,
                "allowed_window_from": device.allowed_window_from,
                "allowed_window_to": device.allowed_window_to,
                "max_shift_min": device.max_shift_min,
            }
            for device in devices
        ])
        return instance_ids

    def _save_programs(self, devices: list[DeviceRecord], instance_ids: dict[str, UUID]) -> dict[tuple[str, str], int]:
        """Zwraca id programów w bazie według pary (device_id, program_id) z pliku."""
        keys, rows = [], []
        for device in devices:
            for program in device.programs:
                keys.append((device.device_id, program.program_id))
                rows.append({
                    "device_instance_id": instance_ids[device.device_id],
                    "source_program_id": program.program_id,
                    "name": program.name,
                    "duration_min": program.duration_min,
                    "profile_kwh": program.profile_kwh,
                })
        return dict(zip(keys, self._insert_returning_ids(DeviceProgram, rows)))

    def _save_actions(
        self,
        devices: list[DeviceRecord],
        instance_ids: dict[str, UUID],
        program_ids: dict[tuple[str, str], int],
    ) -> list[tuple[ActionRecord, int]]:
        """Zwraca pary (akcja, id akcji w bazie)."""
        actions, rows = [], []
        for device in devices:
            for action in device.actions:
                actions.append(action)
                rows.append({
                    "device_instance_id": instance_ids[device.device_id],
                    "device_program_id": program_ids[(device.device_id, action.program_id)] if action.program_id else None,
                    "source_action_id": action.action_id,
                    "action_start": _utc(action.start),
                    "action_end": _utc(action.end),
                    "energy_kwh": action.energy_kwh,
                    "plugged_in": _utc(action.plugged_in),
                    "deadline": _utc(action.deadline),
                })
        return list(zip(actions, self._insert_returning_ids(DeviceAction, rows)))

    def _save_slots(self, energy_data_file_id: UUID, saved_actions: list[tuple[ActionRecord, int]]) -> None:
        self._insert(DeviceSlotUsage, [
            {
                "device_action_id": action_db_id,
                "slot_start": _utc(action.start) + index * SLOT,
                "energy_data_file_id": energy_data_file_id,
                "kwh": kwh,
            }
            for action, action_db_id in saved_actions
            for index, kwh in enumerate(action.slots_kwh)
        ])

    def _insert(self, model, rows: list[dict]) -> None:
        if rows:
            self.db.execute(insert(model), rows)

    def _insert_returning_ids(self, model, rows: list[dict]) -> list[int]:
        """Wsadowy INSERT zwracający id w kolejności wierszy wejściowych."""
        if not rows:
            return []
        statement = insert(model).returning(model.id, sort_by_parameter_order=True)
        return list(self.db.execute(statement, rows).scalars())

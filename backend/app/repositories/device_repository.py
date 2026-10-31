import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, exists, insert
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.orm import Session

from app.models.DeviceAction import DeviceAction
from app.models.DeviceCategory import DeviceCategory  # noqa: F401 - rejestruje tabelę dla FK
from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceInstanceFile import DeviceInstanceFile
from app.models.DeviceProgram import DeviceProgram
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.models.DeviceType import DeviceType  # noqa: F401 - rejestruje tabelę dla FK
from app.parsers.device_records import ActionRecord, DeviceRecord, ProgramRecord


SLOT = timedelta(minutes=15)
# Pola urządzenia i programu, które kolejny import nadpisuje (najnowszy plik wygrywa).
DEVICE_SETTINGS = (
    "name", "device_type", "device_category", "max_power_kw",
    "flexibility_mode", "allowed_window_from", "allowed_window_to", "max_shift_min",
)
PROGRAM_SETTINGS = ("name", "duration_min", "profile_kwh")


def _utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        raise ValueError(f"{moment.isoformat()}: czas bez strefy czasowej")
    return moment.astimezone(timezone.utc)


class DeviceRepository:
    """Urządzenia domu użytkownika i akcje z wgranych plików urządzeń.

    Urządzenie (z programami) jest jedno na device_id w obrębie użytkownika i należy do domu,
    a akcje i ich kwadranse należą do pliku, z którego pochodzą.
    """

    def __init__(self, db: Session):
        self.db = db

    def save_for_file(self, *, user_id: UUID, energy_data_file_id: UUID, devices: list[DeviceRecord]) -> None:
        """Dodaje do bieżącej transakcji urządzenia pliku z programami, akcjami i kwadransami.

        Urządzenie i program już obecne w domu są aktualizowane (najnowszy plik wygrywa), a programy
        nieobecne w nowym pliku zostają, bo mogą ich używać akcje z innych plików. Każda tabela trafia
        do bazy jednym wsadowym INSERT-em. Akcje z kwadransami niepasującymi do czasu trwania,
        z nieznanym programem albo z czasem bez strefy są odrzucane przed pierwszym INSERT-em.
        """
        self._check_records(devices)
        instance_ids = self._upsert_instances(user_id, devices)
        self._link_to_file(instance_ids.values(), energy_data_file_id)
        program_ids = self._upsert_programs(devices, instance_ids)
        saved_actions = self._save_actions(devices, energy_data_file_id, instance_ids, program_ids)
        self._save_slots(energy_data_file_id, saved_actions)

    def delete_devices_only_in_file(self, user_id: UUID, energy_data_file_id: UUID) -> None:
        """Usuwa z domu urządzenia, które nie występują w żadnym innym pliku użytkownika.

        Wywoływane przed usunięciem pliku, w tej samej transakcji. Akcje i kwadranse pliku usuwa
        baza (ON DELETE CASCADE na energy_data_file_id).
        """
        in_file = exists().where(
            DeviceInstanceFile.device_instance_id == DeviceInstance.id,
            DeviceInstanceFile.energy_data_file_id == energy_data_file_id,
        )
        in_other_file = exists().where(
            DeviceInstanceFile.device_instance_id == DeviceInstance.id,
            DeviceInstanceFile.energy_data_file_id != energy_data_file_id,
        )
        self.db.execute(
            delete(DeviceInstance).where(DeviceInstance.user_id == user_id, in_file, ~in_other_file)
        )

    def list_for_user(self, user_id: UUID) -> list[DeviceInstance]:
        return (
            self.db.query(DeviceInstance)
            .filter(DeviceInstance.user_id == user_id)
            .order_by(DeviceInstance.source_device_id)
            .all()
        )

    def list_for_file(self, energy_data_file_id: UUID, user_id: UUID) -> list[DeviceInstance]:
        return (
            self.db.query(DeviceInstance)
            .join(DeviceInstanceFile, DeviceInstanceFile.device_instance_id == DeviceInstance.id)
            .filter(
                DeviceInstanceFile.energy_data_file_id == energy_data_file_id,
                DeviceInstance.user_id == user_id,
            )
            .order_by(DeviceInstance.source_device_id)
            .all()
        )

    def records_for_file(
        self, energy_data_file_id: UUID, user_id: UUID, start_utc: datetime, end_utc: datetime
    ) -> list[DeviceRecord]:
        """Urządzenia pliku z programami i akcjami zaczynającymi się w [start_utc, end_utc)."""
        instances = self.list_for_file(energy_data_file_id, user_id)
        programs = (
            self.db.query(DeviceProgram)
            .filter(DeviceProgram.device_instance_id.in_([instance.id for instance in instances]))
            .all()
        )
        actions = (
            self.db.query(DeviceAction)
            .filter(
                DeviceAction.energy_data_file_id == energy_data_file_id,
                DeviceAction.action_start >= start_utc,
                DeviceAction.action_start < end_utc,
            )
            .order_by(DeviceAction.action_start)
            .all()
        )
        slots = defaultdict(list)
        slot_rows = (
            self.db.query(DeviceSlotUsage.device_action_id, DeviceSlotUsage.kwh)
            .filter(DeviceSlotUsage.device_action_id.in_([action.id for action in actions]))
            .order_by(DeviceSlotUsage.device_action_id, DeviceSlotUsage.slot_start)
        )
        for action_id, kwh in slot_rows:
            slots[action_id].append(kwh)

        program_ids = {program.id: program.source_program_id for program in programs}
        records = {
            instance.id: DeviceRecord(
                device_id=instance.source_device_id,
                name=instance.name,
                device_type=instance.device_type,
                device_category=instance.device_category,
                flexibility_mode=instance.flexibility_mode,
                max_power_kw=instance.max_power_kw,
                allowed_window_from=instance.allowed_window_from,
                allowed_window_to=instance.allowed_window_to,
                max_shift_min=instance.max_shift_min,
            )
            for instance in instances
        }
        for program in programs:
            records[program.device_instance_id].programs.append(ProgramRecord(
                program.source_program_id, program.name, program.duration_min, program.profile_kwh,
            ))
        for action in actions:
            records[action.device_instance_id].actions.append(ActionRecord(
                action_id=action.source_action_id,
                start=action.action_start,
                end=action.action_end,
                energy_kwh=action.energy_kwh,
                slots_kwh=slots[action.id],
                program_id=program_ids.get(action.device_program_id),
                plugged_in=action.plugged_in,
                deadline=action.deadline,
            ))
        return list(records.values())

    @staticmethod
    def _check_records(devices: list[DeviceRecord]) -> None:
        for device in devices:
            program_ids = {program.program_id for program in device.programs}
            for action in device.actions:
                if _utc(action.start) + len(action.slots_kwh) * SLOT != _utc(action.end):
                    raise ValueError(f"{action.action_id}: liczba kwadransów nie odpowiada czasowi trwania akcji")
                if action.program_id is not None and action.program_id not in program_ids:
                    raise ValueError(f"{action.action_id}: urządzenie nie ma programu {action.program_id}")
                for moment in (action.plugged_in, action.deadline):
                    _utc(moment)

    def _upsert_instances(self, user_id: UUID, devices: list[DeviceRecord]) -> dict[str, UUID]:
        """Zwraca id urządzeń w bazie według device_id z pliku: istniejących albo nowo dodanych."""
        if not devices:
            return {}
        rows = [
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
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
        ]
        statement = upsert(DeviceInstance)
        statement = statement.on_conflict_do_update(
            constraint="uq_device_instance_user_device",
            set_={column: statement.excluded[column] for column in DEVICE_SETTINGS},
        ).returning(DeviceInstance.source_device_id, DeviceInstance.id)
        return dict(self.db.execute(statement, rows).all())

    def _link_to_file(self, instance_ids, energy_data_file_id: UUID) -> None:
        self._insert(DeviceInstanceFile, [
            {"device_instance_id": instance_id, "energy_data_file_id": energy_data_file_id}
            for instance_id in instance_ids
        ])

    def _upsert_programs(self, devices: list[DeviceRecord], instance_ids: dict[str, UUID]) -> dict[tuple[str, str], int]:
        """Zwraca id programów w bazie według pary (device_id, program_id) z pliku."""
        rows = [
            {
                "device_instance_id": instance_ids[device.device_id],
                "source_program_id": program.program_id,
                "name": program.name,
                "duration_min": program.duration_min,
                "profile_kwh": program.profile_kwh,
            }
            for device in devices
            for program in device.programs
        ]
        if not rows:
            return {}
        statement = upsert(DeviceProgram)
        statement = statement.on_conflict_do_update(
            constraint="uq_device_program_instance_program",
            set_={column: statement.excluded[column] for column in PROGRAM_SETTINGS},
        ).returning(DeviceProgram.device_instance_id, DeviceProgram.source_program_id, DeviceProgram.id)
        device_ids = {instance_id: device_id for device_id, instance_id in instance_ids.items()}
        return {
            (device_ids[instance_id], program_id): program_db_id
            for instance_id, program_id, program_db_id in self.db.execute(statement, rows).all()
        }

    def _save_actions(
        self,
        devices: list[DeviceRecord],
        energy_data_file_id: UUID,
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
                    "energy_data_file_id": energy_data_file_id,
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

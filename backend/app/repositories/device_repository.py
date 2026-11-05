import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import DateTime, Integer, and_, bindparam, cast, delete, exists, extract, func, insert, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID, insert as upsert
from sqlalchemy.orm import Session

from app.models.DeviceAction import DeviceAction
from app.models.DeviceCategory import DeviceCategory  # noqa: F401 - rejestruje tabelę dla FK
from app.models.DeviceInstance import DeviceInstance
from app.models.DeviceInstanceFile import DeviceInstanceFile
from app.models.DeviceProgram import DeviceProgram
from app.models.DeviceSlotUsage import DeviceSlotUsage
from app.models.DeviceType import DeviceType
from app.models.EnergyDataFile import EnergyDataFile
from app.parsers.device_records import ActionRecord, DeviceRecord, ProgramRecord
from app.parsers.devices import LOCAL_TIMEZONE


SLOT = timedelta(minutes=15)
# Pola urządzenia i programu, które kolejny import nadpisuje (najnowszy plik wygrywa).
DEVICE_SETTINGS = (
    "name", "device_type", "device_category", "max_power_kw",
    "flexibility_mode", "allowed_window_from", "allowed_window_to", "max_shift_min",
)
PROGRAM_SETTINGS = ("name", "duration_min", "profile_kwh")


# Flaga superseded (ZP-81). Kolejność plików to kolejność uploadu: (uploaded_at, id).
_FLAG_BIND_TYPES = {
    "user_id": PG_UUID(as_uuid=True),
    "file_id": PG_UUID(as_uuid=True),
    "device_ids": ARRAY(PG_UUID(as_uuid=True)),
    "start": DateTime(timezone=True),
    "end": DateTime(timezone=True),
}


def _flag_sql(source: str):
    """Zapytanie SQL z typami parametrów, których w nim używa."""
    names = dict.fromkeys(re.findall(r"(?<!:):(\w+)", source))
    return text(source).bindparams(*(bindparam(name, type_=_FLAG_BIND_TYPES[name]) for name in names))


# Dla każdej pary (plik, urządzenie) w zakresie: przedziały, w których nowszy plik z tym urządzeniem
# obejmuje kwadranse swoim okresem.
_COVER_CTE = """
WITH cover AS MATERIALIZED (
    SELECT own.id AS file_id, own_link.device_instance_id AS device_id,
           GREATEST(newer.period_start, :start) AS cover_start,
           LEAST(newer.period_end, :end) AS cover_end
    FROM energy_data_files AS own
    JOIN device_instance_files AS own_link ON own_link.energy_data_file_id = own.id
    JOIN device_instance_files AS newer_link ON newer_link.device_instance_id = own_link.device_instance_id
    JOIN energy_data_files AS newer ON newer.id = newer_link.energy_data_file_id
    WHERE own.user_id = :user_id
      AND own_link.device_instance_id = ANY(:device_ids)
      AND (newer.uploaded_at, newer.id) > (own.uploaded_at, own.id)
      AND newer.period_start < :end AND newer.period_end > :start
)
"""
RESTORE_UNCOVERED = _flag_sql(_COVER_CTE + """
UPDATE device_slot_usage AS slot SET superseded = false
FROM device_actions AS action, energy_data_files AS own
WHERE slot.superseded
  AND action.id = slot.device_action_id AND own.id = slot.energy_data_file_id
  AND own.user_id = :user_id AND action.device_instance_id = ANY(:device_ids)
  AND slot.slot_start >= :start AND slot.slot_start < :end
  AND NOT EXISTS (
      SELECT 1 FROM cover
      WHERE cover.file_id = slot.energy_data_file_id AND cover.device_id = action.device_instance_id
        AND slot.slot_start >= cover.cover_start AND slot.slot_start < cover.cover_end
  )
""")
MARK_COVERED = _flag_sql(_COVER_CTE + """
UPDATE device_slot_usage AS slot SET superseded = true
FROM cover, device_actions AS action
WHERE slot.energy_data_file_id = cover.file_id AND NOT slot.superseded
  AND slot.slot_start >= cover.cover_start AND slot.slot_start < cover.cover_end
  AND action.id = slot.device_action_id AND action.device_instance_id = cover.device_id
""")
NEWER_FILE_EXISTS = _flag_sql("""
SELECT EXISTS (
    SELECT 1
    FROM energy_data_files AS new_file, device_instance_files AS link
    JOIN energy_data_files AS newer ON newer.id = link.energy_data_file_id
    WHERE new_file.id = :file_id AND link.device_instance_id = ANY(:device_ids)
      AND (newer.uploaded_at, newer.id) > (new_file.uploaded_at, new_file.id)
      AND newer.period_start < :end AND newer.period_end > :start
)
""")


def _local_day_and_slot(column):
    local = func.timezone(LOCAL_TIMEZONE.key, column)
    slot = func.floor((extract("hour", local) * 60 + extract("minute", local)) / (SLOT.seconds // 60))
    return func.to_char(local, "YYYY-MM-DD"), cast(slot, Integer)


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
        period = self._file_period(energy_data_file_id, devices)
        if period is None:
            return
        device_ids = list(instance_ids.values())
        if self._has_newer_file(energy_data_file_id, device_ids, *period):
            # Plik wgrany z wcześniejszą datą niż istniejące (np. w testach): pełne przeliczenie okresu.
            self.refresh_superseded(user_id, device_ids, *period)
        else:
            self._cover_older_files(user_id, energy_data_file_id, device_ids, *period)

    def refresh_superseded(self, user_id: UUID, device_ids: list[UUID], start_utc: datetime, end_utc: datetime) -> None:
        """Przelicza flagę superseded kwadransów urządzeń `device_ids` w [start_utc, end_utc).

        Kwadrans urządzenia należy do najnowszego pliku (kolejność uploadu), który zawiera to
        urządzenie i obejmuje ten kwadrans swoim okresem; wersje z pozostałych plików są przykryte.
        Najpierw wyznacza przedziały przykrycia dla par (plik, urządzenie) - jest ich kilka, a nie
        setki tysięcy jak kwadransów - i zmienia tylko wiersze, których flaga ma się zmienić.
        Wywoływane w transakcji usunięcia pliku, dla urządzeń i okresu tego pliku.
        """
        if not device_ids:
            return
        self.db.flush()
        params = self._flag_params(user_id=user_id, device_ids=device_ids, start=start_utc, end=end_utc)
        self.db.execute(RESTORE_UNCOVERED, params)
        self.db.execute(MARK_COVERED, params)

    def _cover_older_files(
        self, user_id: UUID, energy_data_file_id: UUID, device_ids: list[UUID], start_utc: datetime, end_utc: datetime
    ) -> None:
        """Nowy plik jest najnowszy: jego kwadranse obowiązują, a starsze wersje w jego okresie są przykryte.

        Upload nie przywraca żadnego wiersza, więc wystarczy oznaczyć te, które jeszcze nie są przykryte.
        Plik, którego wszystkie urządzenia są w nowym pliku (typowy przypadek: ten sam dom), jest
        oznaczany bez sprawdzania urządzenia każdego wiersza.
        """
        self.db.flush()
        new_file = self.db.get(EnergyDataFile, energy_data_file_id)
        older_ids = self.db.execute(
            select(EnergyDataFile.id).where(
                EnergyDataFile.user_id == user_id,
                tuple_(EnergyDataFile.uploaded_at, EnergyDataFile.id) < tuple_(new_file.uploaded_at, new_file.id),
            )
        ).scalars().all()
        new_devices = set(device_ids)
        for file_id, file_devices in self.device_ids_by_file(older_ids).items():
            if not file_devices & new_devices:
                continue
            statement = update(DeviceSlotUsage).where(
                DeviceSlotUsage.energy_data_file_id == file_id,
                DeviceSlotUsage.superseded.is_(False),
                DeviceSlotUsage.slot_start >= _utc(start_utc),
                DeviceSlotUsage.slot_start < _utc(end_utc),
            )
            if not file_devices <= new_devices:
                statement = statement.where(DeviceSlotUsage.device_action_id.in_(
                    select(DeviceAction.id).where(
                        DeviceAction.energy_data_file_id == file_id,
                        DeviceAction.device_instance_id.in_(file_devices & new_devices),
                    )
                ))
            self.db.execute(statement.values(superseded=True).execution_options(synchronize_session=False))

    def _has_newer_file(self, energy_data_file_id: UUID, device_ids: list[UUID], start_utc: datetime, end_utc: datetime) -> bool:
        self.db.flush()
        params = self._flag_params(device_ids=device_ids, start=start_utc, end=end_utc)
        return self.db.execute(NEWER_FILE_EXISTS, {**params, "file_id": energy_data_file_id}).scalar()

    @staticmethod
    def _flag_params(*, device_ids: list[UUID], start: datetime, end: datetime, user_id: UUID | None = None) -> dict:
        params = {"device_ids": list(device_ids), "start": _utc(start), "end": _utc(end)}
        if user_id is not None:
            params["user_id"] = user_id
        return params

    def _file_period(self, energy_data_file_id: UUID, devices: list[DeviceRecord]) -> tuple[datetime, datetime] | None:
        """Okres pliku z energy_data_files, a gdy go nie zapisano - od pierwszej do ostatniej akcji."""
        self.db.flush()
        start, end = self.db.execute(
            select(EnergyDataFile.period_start, EnergyDataFile.period_end).where(EnergyDataFile.id == energy_data_file_id)
        ).one()
        if start is not None and end is not None:
            return start, end
        actions = [action for device in devices for action in device.actions]
        if not actions:
            return None
        return min(_utc(action.start) for action in actions), max(_utc(action.end) for action in actions)

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

    def device_ids_by_file(self, file_ids: list[UUID]) -> dict[UUID, set[UUID]]:
        rows = self.db.execute(
            select(DeviceInstanceFile.energy_data_file_id, DeviceInstanceFile.device_instance_id)
            .where(DeviceInstanceFile.energy_data_file_id.in_(file_ids))
        )
        devices = defaultdict(set)
        for file_id, device_id in rows:
            devices[file_id].add(device_id)
        return devices

    def slot_usage(
        self, file_ids: list[UUID], start_utc: datetime, end_utc: datetime, *, current_only: bool
    ) -> list[tuple[datetime, UUID, float]]:
        """Kwadranse urządzeń (początek w UTC, urządzenie, kWh) w [start_utc, end_utc).

        `current_only` pomija wersje przykryte nowszym plikiem (dane „Wszystkich plików urządzeń”).
        """
        query = (
            select(DeviceSlotUsage.slot_start, DeviceAction.device_instance_id, DeviceSlotUsage.kwh)
            .join(DeviceAction, DeviceAction.id == DeviceSlotUsage.device_action_id)
            .where(
                DeviceSlotUsage.energy_data_file_id.in_(file_ids),
                DeviceSlotUsage.slot_start >= _utc(start_utc),
                DeviceSlotUsage.slot_start < _utc(end_utc),
            )
        )
        if current_only:
            query = query.where(DeviceSlotUsage.superseded.is_(False))
        return self.db.execute(query).all()

    def instances_with_type_labels(self, instance_ids: list[UUID]) -> list[tuple[DeviceInstance, str]]:
        return self.db.execute(
            select(DeviceInstance, DeviceType.label)
            .join(DeviceType, DeviceType.code == DeviceInstance.device_type)
            .where(DeviceInstance.id.in_(instance_ids))
        ).all()

    def merged_grid_import(self, file_ids: list[UUID]) -> list[tuple[str, int, float]]:
        """Pobór z sieci (dzień lokalny, kwadrans, kWh) z obowiązujących wersji urządzeń plików.

        Jak przy imporcie pliku: w każdym kwadransie produkcja PV najpierw pokrywa zużycie,
        więc pobór = max(0, suma energii urządzeń).
        """
        net = (
            select(DeviceSlotUsage.slot_start, func.sum(DeviceSlotUsage.kwh).label("kwh"))
            .where(DeviceSlotUsage.energy_data_file_id.in_(file_ids), DeviceSlotUsage.superseded.is_(False))
            .group_by(DeviceSlotUsage.slot_start)
            .subquery()
        )
        day, slot = _local_day_and_slot(net.c.slot_start)
        return self.db.execute(
            select(day.label("day"), slot.label("slot"), func.sum(func.greatest(net.c.kwh, 0.0)))
            .group_by("day", "slot")
        ).all()

    def merged_actions_per_day(self, file_ids: list[UUID]) -> dict[str, int]:
        """Liczba akcji w dniach lokalnych; akcja obowiązuje, gdy obowiązuje jej pierwszy kwadrans."""
        day, _ = _local_day_and_slot(DeviceAction.action_start)
        rows = self.db.execute(
            select(day.label("day"), func.count())
            .join(DeviceSlotUsage, and_(
                DeviceSlotUsage.device_action_id == DeviceAction.id,
                DeviceSlotUsage.slot_start == DeviceAction.action_start,
            ))
            .where(DeviceAction.energy_data_file_id.in_(file_ids), DeviceSlotUsage.superseded.is_(False))
            .group_by("day")
        ).all()
        return dict(sorted(rows))

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

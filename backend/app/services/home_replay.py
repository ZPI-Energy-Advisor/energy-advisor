"""Przebiegi run_profile z historii: kwadranse akcji z pliku zamienione na profile dla huba.

Każda akcja to przebieg z profilem jej kwadransów, zaplanowany na jej start (`start_at`). Profil bierzemy
z `device_slot_usage`, czyli tego samego rozkładu na kwadranse co wycena i wykresy, więc energia przebiegów
jest równa energii z pliku.

Urządzeniami stałymi w symulacji steruje użytkownik, a z historii idzie tylko produkcja PV: z dnia
referencyjnego na dobę planu przy wykonaniu planu (ZP-113). Przy ustawieniu doby na zegarze niczego
nie odtwarzamy.
"""

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

from app.parsers.devices import LOCAL_TIMEZONE
from app.schemas.plan_run import PlanRunReplay
from app.schemas.smart_home import CommandType, HubCommand, HubCommandResult, HubCommandStatus, ReplaySlot
from app.services.plan_history import moved_to


SLOT = timedelta(minutes=15)
# Kod huba dla urządzenia spoza jego rejestru: tylko takie urządzenia trafiają do skipped_devices.
DEVICE_NOT_FOUND = "device_not_found"


@dataclass
class ReplayRun:
    """Przebieg dla huba: start, energia kolejnych kwadransów i action_id z pliku, który wróci w zdarzeniach."""

    device_id: str
    start: datetime
    ref: str
    profile_kwh: list[float] = field(default_factory=list)

    @property
    def end(self) -> datetime:
        return self.start + SLOT * len(self.profile_kwh)


def replay_runs(slots: list[ReplaySlot]) -> list[ReplayRun]:
    """Przebiegi z kwadransów akcji, posortowane po starcie.

    - Akcja zaczęta przed dobą (np. lampa 23:00–1:00) ma tylko kwadranse od północy, więc rusza o północy
      z resztą profilu.
    - Przerwa w kwadransach akcji (część przykryta nowszym plikiem) dzieli ją na osobne przebiegi.
    - Nachodzące na siebie przebiegi jednego urządzenia łączymy w jeden, bo urządzenie nie wykona dwóch
      przebiegów naraz; sąsiednie (koniec jednego = start drugiego) zostają osobne.
    """
    by_action: dict[tuple[str, int], list[ReplaySlot]] = defaultdict(list)
    for slot in slots:
        by_action[(slot.device_id, slot.action_id)].append(slot)

    by_device: dict[str, list[ReplayRun]] = defaultdict(list)
    for (device_id, _), action_slots in by_action.items():
        by_device[device_id].extend(_contiguous_runs(sorted(action_slots, key=lambda slot: slot.slot_start)))

    runs = []
    for device_runs in by_device.values():
        runs.extend(_merge_overlapping(sorted(device_runs, key=lambda run: run.start)))
    return sorted(runs, key=lambda run: (run.start, run.device_id))


def _contiguous_runs(slots: list[ReplaySlot]) -> list[ReplayRun]:
    runs: list[ReplayRun] = []
    for slot in slots:
        if not runs or runs[-1].end != slot.slot_start:
            runs.append(ReplayRun(device_id=slot.device_id, start=slot.slot_start, ref=slot.ref))
        runs[-1].profile_kwh.append(slot.kwh)
    return runs


def _merge_overlapping(runs: list[ReplayRun]) -> list[ReplayRun]:
    merged: list[ReplayRun] = []
    for run in runs:
        current = merged[-1] if merged else None
        if current is None or run.start >= current.end:
            merged.append(ReplayRun(device_id=run.device_id, start=run.start, ref=run.ref, profile_kwh=list(run.profile_kwh)))
            continue
        offset = int((run.start - current.start) / SLOT)
        missing = offset + len(run.profile_kwh) - len(current.profile_kwh)
        current.profile_kwh.extend([0.0] * max(missing, 0))
        for index, kwh in enumerate(run.profile_kwh):
            current.profile_kwh[offset + index] += kwh
    return merged


def moved_runs(runs: list[ReplayRun], source_day: date, target_day: date) -> list[ReplayRun]:
    """Przebiegi z doby `source_day` przeniesione na te same godziny zegarowe doby `target_day`.

    Tak plan na jutro dostaje produkcję PV: jutro nie ma historii, więc bierzemy dzień referencyjny.
    """
    if source_day == target_day:
        return runs
    return [
        replace(run, start=moved_to(run.start, source_day, target_day).astimezone(timezone.utc)) for run in runs
    ]


def replay_commands(runs: list[ReplayRun]) -> list[HubCommand]:
    """Przebiegi jako komendy run_profile huba: start akcji w `start_at`, action_id z pliku w `ref`."""
    return [
        HubCommand(
            device_id=run.device_id,
            command=CommandType.RUN_PROFILE,
            profile_kwh=run.profile_kwh,
            ref=run.ref,
            start_at=run.start.astimezone(LOCAL_TIMEZONE),
        )
        for run in runs
    ]


def replay_summary(runs: list[ReplayRun], results: list[HubCommandResult]) -> PlanRunReplay:
    """Opis odtworzenia z wyników huba dla komend z `replay_commands(runs)`, w tej samej kolejności.

    Urządzenie spoza rejestru huba (np. przy zaległej wysyłce) trafia do `skipped_devices`; inne odrzucenie
    pojedynczego przebiegu (np. zajęte urządzenie) liczymy w `rejected_actions`.
    """
    replayed, skipped = set(), set()
    actions = rejected = 0
    for run, result in zip(runs, results, strict=True):
        if result.status != HubCommandStatus.REJECTED:
            actions += 1
            replayed.add(run.device_id)
        elif result.code == DEVICE_NOT_FOUND:
            skipped.add(run.device_id)
        else:
            rejected += 1
    return PlanRunReplay(actions=actions, devices=len(replayed), skipped_devices=sorted(skipped), rejected_actions=rejected)

"""Odtworzenie doby z historii: akcje urządzeń fixed jako przebiegi run_profile dla huba.

Urządzenia fixed (PV, oświetlenie, lodówka…) nie podlegają optymalizacji, więc symulacja powtarza ich
akcje z pliku: każda akcja to przebieg z profilem jej kwadransów, zaplanowany na jej start (`start_at`).
Profil bierzemy z `device_slot_usage`, czyli tego samego rozkładu na kwadranse co wycena i wykresy,
dzięki czemu energia odtworzonej doby jest równa energii z pliku.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.schemas.smart_home import ReplaySlot


SLOT = timedelta(minutes=15)


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

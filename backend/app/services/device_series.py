"""Seria urządzeń źródła w tablicach numpy i jej pamięć w procesie serwera (ZP-147).

Wykres urządzeń przy każdej zmianie poziomu, zakresu albo rozdzielczości liczy to samo: kWh każdego urządzenia
w każdym kwadransie źródła. Wiersze „urządzenie × kwadrans” (rok to ok. 200 tys.) czytamy z bazy raz na źródło
i trzymamy jako tablice; kolejne zapytania tylko je filtrują i sumują (np.bincount), bez pętli po wierszach.

Klucz pamięci to zestaw plików źródła (identyfikator, czas wgrania, status) i tryb „tylko obowiązujące wersje”.
Wgranie, usunięcie albo przykrycie pliku nowszym zmienia ten zestaw, więc stara pozycja przestaje pasować także
w innych procesach serwera; `forget_user` dodatkowo zwalnia pamięć po zmianie plików użytkownika.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import numpy as np

from app.parsers.devices import LOCAL_TIMEZONE

# Ile źródeł pamiętamy: rok urządzeń to kilka MB tablic, a jeden użytkownik przełącza zwykle 1–2 źródła.
SERIES_CACHE_LIMIT = 8


@dataclass(frozen=True)
class DeviceSeries:
    """Wiersze źródła: kwadrans (indeks w `slot_seconds`), urządzenie (indeks w `device_ids`) i kWh.

    Kolejność wierszy jest taka jak w bazie, więc sumy po kwadransach i grupach wychodzą w tej samej kolejności
    dodawania co w dawnej pętli (te same wartości float). Dla każdego kwadransu znamy też lokalny dzień
    (`slot_day`, ISO i numer dnia `slot_ordinal`) i numer kwadransu doby (`slot_quarter`), jak w seriach usage_15min.
    """

    slot_seconds: np.ndarray
    slot_day: list[str]
    slot_ordinal: np.ndarray
    slot_quarter: np.ndarray
    row_slot: np.ndarray
    row_device: np.ndarray
    kwh: np.ndarray
    device_ids: list[UUID]
    # kWh każdego wiersza jako Decimal(str(kWh)), jak w dawnym liczeniu rozbicia kosztu; liczone raz na serię.
    kwh_decimal: list[Decimal]

    @classmethod
    def from_rows(cls, rows: list[tuple[int, UUID, float]]) -> "DeviceSeries":
        seconds = np.fromiter((row[0] for row in rows), dtype=np.int64, count=len(rows))
        kwh = np.fromiter((row[2] for row in rows), dtype=np.float64, count=len(rows))
        device_index: dict[UUID, int] = {}
        row_device = np.fromiter(
            (device_index.setdefault(row[1], len(device_index)) for row in rows), dtype=np.int32, count=len(rows)
        )
        slot_seconds, row_slot = np.unique(seconds, return_inverse=True)
        local = [datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone(LOCAL_TIMEZONE) for value in slot_seconds]
        return cls(
            slot_seconds=slot_seconds,
            slot_day=[moment.date().isoformat() for moment in local],
            slot_ordinal=np.fromiter((moment.toordinal() for moment in local), dtype=np.int64, count=len(local)),
            slot_quarter=np.fromiter((moment.hour * 4 + moment.minute // 15 for moment in local), dtype=np.int64, count=len(local)),
            row_slot=row_slot.astype(np.int64).reshape(-1),
            row_device=row_device,
            kwh=kwh,
            device_ids=list(device_index),
            kwh_decimal=[Decimal(str(row[2])) for row in rows],
        )

    def slot_datetime(self, slot: int) -> datetime:
        return datetime.fromtimestamp(int(self.slot_seconds[slot]), tz=timezone.utc)

    def slots_between(self, start: datetime, end: datetime) -> np.ndarray:
        """Maska kwadransów w [start, end)."""
        return (self.slot_seconds >= int(start.timestamp())) & (self.slot_seconds < int(end.timestamp()))


SourceKey = tuple


def source_key(files, current_only: bool) -> SourceKey:
    return (
        current_only,
        tuple(sorted((str(item.id), item.uploaded_at.isoformat() if item.uploaded_at else "", item.status) for item in files)),
    )


class _SeriesCache:
    def __init__(self, limit: int):
        self.limit = limit
        self._entries: OrderedDict[SourceKey, tuple[UUID, DeviceSeries]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: SourceKey) -> DeviceSeries | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, key: SourceKey, user_id: UUID, series: DeviceSeries) -> None:
        with self._lock:
            self._entries[key] = (user_id, series)
            self._entries.move_to_end(key)
            while len(self._entries) > self.limit:
                self._entries.popitem(last=False)

    def forget_user(self, user_id: UUID) -> None:
        with self._lock:
            for key in [key for key, (owner, _) in self._entries.items() if owner == user_id]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


series_cache = _SeriesCache(SERIES_CACHE_LIMIT)


def forget_user_series(user_id: UUID) -> None:
    """Po wgraniu albo usunięciu pliku urządzeń: zwalnia pamięć serii użytkownika."""
    series_cache.forget_user(user_id)

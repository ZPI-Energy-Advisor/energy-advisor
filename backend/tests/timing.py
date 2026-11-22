import os
import time
from decimal import Decimal

# Limity testów wydajności są dobrane na maszynie, na której zadanie kalibracyjne trwa REFERENCE_SECONDS.
# Wolniejsza maszyna (inny laptop, Docker na Windowsie, obciążony CI) dostaje proporcjonalnie wyższe limity,
# więc test dalej łapie regresję względem szybkości tej samej maszyny, a nie samą wolniejszą maszynę.
REFERENCE_SECONDS = 0.052
BASE_SCALE = 2.0 if os.getenv("CI") else 1.5


def _calibration_workload() -> Decimal:
    total = Decimal(0)
    buckets: dict[int, Decimal] = {}
    for index in range(70_000):
        value = Decimal(index) * Decimal("1.23") / Decimal(7)
        total += value
        buckets[index % 96] = buckets.get(index % 96, Decimal(0)) + value
    return total


def machine_factor() -> float:
    best = float("inf")
    for _ in range(5):
        started = time.perf_counter()
        _calibration_workload()
        best = min(best, time.perf_counter() - started)
    return max(1.0, best / REFERENCE_SECONDS)


MACHINE_FACTOR = machine_factor()
TIME_LIMIT_SCALE = float(os.getenv("PERF_TIME_SCALE") or BASE_SCALE * MACHINE_FACTOR)

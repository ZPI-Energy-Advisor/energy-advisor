"""Sprawdza plik urządzeń (JSON) z regułami formatu i wypisuje podsumowanie.

Reguły opisuje docs/devices-file-format.md, a ich kod jest w app/parsers/device_validation.py
(używa go też import pliku w aplikacji). Ten skrypt tylko wczytuje plik i wypisuje wynik.

Użycie (z katalogu projektu):
    python backend/scripts/validate_devices_file.py frontend/public/samples/devices-example.json
    python backend/scripts/validate_devices_file.py plik.json --max-grid-kw 12

Zwraca kod 0, gdy plik jest poprawny, i 1, gdy znaleziono błędy.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parsers.device_validation import DEFAULT_MAX_GRID_KW, PRODUCER_CATEGORY, validate_document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Walidacja pliku urządzeń (JSON).")
    parser.add_argument("path", help="ścieżka do pliku urządzeń")
    parser.add_argument("--max-grid-kw", type=float, default=DEFAULT_MAX_GRID_KW,
                        help="limit mocy przyłącza (domyślnie 9 kW)")
    args = parser.parse_args()

    try:
        with open(args.path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"Nie udało się wczytać pliku: {error}")
        return 1

    result = validate_document(document, args.max_grid_kw)
    if not result.is_valid:
        print(f"Znaleziono błędy ({len(result.errors)}):")
        print("\n".join(f"  - {error}" for error in result.errors))
        return 1

    idle = f", bez akcji: {', '.join(result.idle_devices)}" if result.idle_devices else ""
    print(f"OK: {result.devices_count} urządzeń, {len(result.categories)} kategorii, "
          f"{result.actions_count} akcji{idle}")
    if result.peak_kw is not None:
        print(f"Szczyt poboru: {result.peak_kw:.2f} kW o {result.peak_at:%d.%m %H:%M} (limit {args.max_grid_kw} kW)")
    for day, categories in result.daily_energy.items():
        consumption = sum(value for category, value in categories.items() if category != PRODUCER_CATEGORY)
        details = ", ".join(f"{category} {value:.2f}" for category, value in sorted(categories.items()))
        print(f"{day}: pobór {consumption:.2f} kWh | {details}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

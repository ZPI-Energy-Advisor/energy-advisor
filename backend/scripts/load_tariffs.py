"""Ładuje cennik z plików JSON do bazy (ZP-99).

Uruchomienie z katalogu backend:

    python scripts/load_tariffs.py data/tariffs            # waliduje i ładuje wszystkie pliki
    python scripts/load_tariffs.py --check data/tariffs    # tylko walidacja i pokrycie dni, bez bazy
    python scripts/load_tariffs.py data/tariffs/2026/pge.json data/tariffs/2026/regulatory.json

Wszystkie pliki ładują się w jednej transakcji; błąd w którymkolwiek oznacza brak zmian w bazie. Plik zastępuje
dane w swoim zakresie dat (`covers`), więc ponowne ładowanie nie tworzy duplikatów. Format plików:
docs/tariff-data-format.md.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.tariff_data.build import completeness_errors, coverage  # noqa: E402
from app.tariff_data.files import TariffDataError, read_data_set  # noqa: E402

DATA_START = date(2024, 8, 24)
DATA_END = date(2026, 12, 31)


def _print_coverage(data_set) -> None:
    from app.services.tariff_engine import format_day_ranges

    for operator, codes in sorted(coverage(data_set).items(), key=lambda item: item[0].value):
        for code, days in sorted(codes.items(), key=lambda item: item[0].value):
            print(f"  {operator.value:7} {code.value:8} {format_day_ranges(days)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ładowanie cennika z plików JSON do bazy.")
    parser.add_argument("paths", nargs="+", type=Path, help="pliki JSON albo katalogi (np. data/tariffs)")
    parser.add_argument("--check", action="store_true", help="tylko walidacja, bez zapisu do bazy")
    parser.add_argument(
        "--complete",
        action="store_true",
        help=f"sprawdź też pełne pokrycie dni {DATA_START.isoformat()} – {DATA_END.isoformat()}",
    )
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    try:
        data_set = read_data_set(args.paths)
    except TariffDataError as exc:
        print(f"Błędy w plikach cennika ({len(exc.errors)}):", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"Pliki poprawne: {len(data_set.operator_files)} operatorów, {len(data_set.regulatory_files)} opłat regulacyjnych."
    )
    _print_coverage(data_set)
    if args.complete:
        missing = completeness_errors(data_set, DATA_START, DATA_END)
        if missing:
            print("Niepełne pokrycie dni:", file=sys.stderr)
            for error in missing:
                print(f"  - {error}", file=sys.stderr)
            return 1
        print(f"Pełne pokrycie {DATA_START.isoformat()} – {DATA_END.isoformat()}.")
    if args.check:
        return 0

    from app.database import SessionLocal
    from app.tariff_data.db import load_data_set

    with SessionLocal() as session:
        try:
            summaries = load_data_set(session, data_set)
            session.commit()
        except TariffDataError as exc:
            session.rollback()
            print("Nie załadowano cennika (baza bez zmian):", file=sys.stderr)
            for error in exc.errors:
                print(f"  - {error}", file=sys.stderr)
            return 1
        except Exception:
            session.rollback()
            raise
    for summary in summaries:
        print(f"  {summary.file}: usunięto {summary.removed}, wstawiono {summary.inserted}")
    print("Cennik załadowany.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

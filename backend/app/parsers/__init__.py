import pandas as pd

from app.parsers.base import (
    KWH,
    TIMESTAMP_START,
    EnergyFileParser,
    FileImportError,
    ImportReport,
    ParsedEnergyFile,
)
from app.parsers.formats import MeterExportParser, SimpleCsvParser, TauronV1Parser, TauronV2Parser
from app.parsers.reading import HOURLY_RESOLUTION, QUARTER_HOUR_RESOLUTION, read_table


PARSERS: list[EnergyFileParser] = [TauronV1Parser(), TauronV2Parser(), SimpleCsvParser(), MeterExportParser()]


def detect_parser(table: pd.DataFrame) -> EnergyFileParser:
    for parser in PARSERS:
        if parser.detect(table):
            return parser
    raise FileImportError(422, "Nierozpoznany format pliku. Brak wymaganych kolumn.")


def parse_energy_file(file_obj) -> ParsedEnergyFile:
    table = read_table(file_obj)
    return detect_parser(table).parse(table)


__all__ = [
    "HOURLY_RESOLUTION",
    "KWH",
    "PARSERS",
    "QUARTER_HOUR_RESOLUTION",
    "TIMESTAMP_START",
    "EnergyFileParser",
    "FileImportError",
    "ImportReport",
    "ParsedEnergyFile",
    "detect_parser",
    "parse_energy_file",
    "read_table",
]

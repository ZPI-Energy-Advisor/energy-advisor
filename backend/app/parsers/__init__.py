import pandas as pd

from app.parsers.base import (
    KWH,
    TIMESTAMP_START,
    UNIT_ACTION,
    UNIT_ROW,
    DeviceData,
    DocumentParser,
    EnergyFileParser,
    FileImportError,
    ImportReport,
    ParsedEnergyFile,
)
from app.parsers.devices import DevicesJsonParser
from app.parsers.formats import MeterExportParser, SimpleCsvParser, TauronV1Parser, TauronV2Parser
from app.parsers.reading import HOURLY_RESOLUTION, QUARTER_HOUR_RESOLUTION, read_document, read_table


# Parsery tabelaryczne dostają tabelę z pliku CSV, parsery dokumentowe - wczytany dokument JSON.
PARSERS: list[EnergyFileParser] = [TauronV1Parser(), TauronV2Parser(), SimpleCsvParser(), MeterExportParser()]
DOCUMENT_PARSERS: list[DocumentParser] = [DevicesJsonParser()]


def detect_parser(table: pd.DataFrame) -> EnergyFileParser:
    for parser in PARSERS:
        if parser.detect(table):
            return parser
    raise FileImportError(422, "Nierozpoznany format pliku. Brak wymaganych kolumn.")


def detect_document_parser(document) -> DocumentParser:
    if isinstance(document, dict):
        for parser in DOCUMENT_PARSERS:
            if parser.detect(document):
                return parser
    raise FileImportError(422, "Nierozpoznany format pliku JSON. Plik urządzeń wymaga pól devices i energy_usage.")


def parse_energy_file(file_obj) -> ParsedEnergyFile:
    document = read_document(file_obj)
    if document is not None:
        return detect_document_parser(document).parse(document)
    table = read_table(file_obj)
    return detect_parser(table).parse(table)


__all__ = [
    "DOCUMENT_PARSERS",
    "HOURLY_RESOLUTION",
    "KWH",
    "PARSERS",
    "QUARTER_HOUR_RESOLUTION",
    "TIMESTAMP_START",
    "UNIT_ACTION",
    "UNIT_ROW",
    "DeviceData",
    "DevicesJsonParser",
    "DocumentParser",
    "EnergyFileParser",
    "FileImportError",
    "ImportReport",
    "ParsedEnergyFile",
    "detect_document_parser",
    "detect_parser",
    "parse_energy_file",
    "read_document",
    "read_table",
]

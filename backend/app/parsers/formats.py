import pandas as pd

from app.parsers.base import KWH, TIMESTAMP_START, EnergyFileParser, FileImportError, ImportReport, ParsedEnergyFile
from app.parsers.reading import ROW_ERRORS, YEAR_FIRST_DATE, detect_resolution_minutes, parse_reading_ends


CONSUMPTION_KINDS = 'pobór|pobor|pobrana'
DATE_SAMPLE_SIZE = 20

NO_ROWS = "Plik nie zawiera żadnych odczytów."
NO_CONSUMPTION_ROWS = "Plik zawiera tylko dane o oddaniu energii (brak poboru) lub dane są puste."
DATES_NOT_RECOGNIZED = (
    "Nie rozpoznano formatu dat w pliku. Obsługiwane formaty: RRRR-MM-DD GG:MM, "
    "DD.MM.RRRR GG:MM (także z / lub -) oraz daty liczbowe z Excela."
)


def _quoted(values: pd.Series) -> pd.Series:
    return "„" + values.astype(str).str.strip().str.slice(0, 40) + "”"


class MeterReadingsParser(EnergyFileParser):
    date_column: str
    value_column: str
    kind_column: str

    def _column(self, table: pd.DataFrame, name: str) -> str | None:
        return next((column for column in table.columns if column.casefold() == name.casefold()), None)

    def has_columns(self, table: pd.DataFrame) -> bool:
        return all(self._column(table, name) for name in (self.date_column, self.value_column, self.kind_column))

    def detect(self, table: pd.DataFrame) -> bool:
        return self.has_columns(table)

    def parse(self, table: pd.DataFrame) -> ParsedEnergyFile:
        report = ImportReport(detected_format=self.name, format_label=self.label, rows_total=len(table))
        if table.empty:
            raise FileImportError(400, NO_ROWS)

        dates = table[self._column(table, self.date_column)]
        values = table[self._column(table, self.value_column)]
        kinds = table[self._column(table, self.kind_column)]
        reasons = pd.Series(None, index=table.index, dtype=object)

        missing = dates.isna() | values.isna() | kinds.isna()
        reasons[missing] = "brak daty, wartości lub rodzaju energii"
        for line, reason in table.attrs.get(ROW_ERRORS, {}).items():
            reasons[line] = reason

        consumption = ~missing & kinds.astype(str).str.lower().str.contains(CONSUMPTION_KINDS, na=False)
        report.rows_ignored = int((~missing & ~consumption).sum())

        normalized = values.astype(str).str.replace(r'[\s ]', '', regex=True).str.replace(',', '.', regex=False)
        kwh = pd.to_numeric(normalized, errors='coerce')
        invalid_value = consumption & kwh.isna()
        negative_value = consumption & (kwh < 0)
        reasons[invalid_value] = "nieprawidłowa wartość zużycia: " + _quoted(values[invalid_value])
        reasons[negative_value] = "ujemna wartość zużycia: " + _quoted(values[negative_value])
        valid = consumption & ~invalid_value & ~negative_value

        if not valid.any():
            if consumption.any():
                first = reasons[consumption].dropna()
                raise FileImportError(
                    422,
                    "Żaden wiersz z poborem energii nie ma poprawnej wartości zużycia "
                    f"(np. wiersz {first.index[0]}: {first.iloc[0]}).",
                )
            if reasons.notna().all():
                raise FileImportError(
                    422,
                    f"Nie udało się odczytać żadnego wiersza (np. wiersz {reasons.index[0]}: {reasons.iloc[0]}).",
                )
            raise FileImportError(400, NO_CONSUMPTION_ROWS)

        reading_ends = parse_reading_ends(dates[valid])
        if reading_ends.isna().all():
            raise FileImportError(422, DATES_NOT_RECOGNIZED)

        invalid_date = reading_ends.index[reading_ends.isna()]
        reasons[invalid_date] = "nieprawidłowa data: " + _quoted(dates[invalid_date])
        reading_ends = reading_ends.dropna()

        readings = pd.DataFrame({"end": reading_ends, KWH: kwh[reading_ends.index]})
        first_line = readings.reset_index().groupby(["end", KWH])["index"].transform("first")
        first_line.index = readings.index
        duplicate = readings.duplicated(keep="first")
        reasons[readings.index[duplicate]] = "powtórzony odczyt (taki sam jak w wierszu " + first_line[duplicate].astype(str) + ")"
        readings = readings[~duplicate]

        resolution = detect_resolution_minutes(readings["end"])
        data = pd.DataFrame({
            TIMESTAMP_START: readings["end"] - pd.Timedelta(minutes=resolution),
            KWH: readings[KWH],
        }).reset_index(drop=True)

        report.rows_imported = len(data)
        report.resolution_minutes = resolution
        report.add_skipped(reasons.dropna())
        return ParsedEnergyFile(data=data, resolution_minutes=resolution, report=report)


class TauronParser(MeterReadingsParser):
    date_column = "Data i godzina"
    value_column = "Wartosc[kWh/kvar]"
    kind_column = "Rodzaj energii"
    year_first_dates: bool

    def detect(self, table: pd.DataFrame) -> bool:
        return self.has_columns(table) and self._dates_are_year_first(table) == self.year_first_dates

    def _dates_are_year_first(self, table: pd.DataFrame) -> bool:
        sample = table[self._column(table, self.date_column)].dropna().astype(str).head(DATE_SAMPLE_SIZE)
        return not sample.empty and sample.str.match(YEAR_FIRST_DATE).mean() > 0.5


class TauronV1Parser(TauronParser):
    name = "tauron_v1"
    label = "Tauron eLicznik – daty DD.MM.RRRR"
    year_first_dates = False


class TauronV2Parser(TauronParser):
    name = "tauron_v2"
    label = "Tauron eLicznik – daty RRRR-MM-DD"
    year_first_dates = True


class SimpleCsvParser(MeterReadingsParser):
    name = "prosty_csv"
    label = "Prosty CSV (Data; Wartość kWh; Rodzaj)"
    date_column = "Data"
    value_column = "Wartość kWh"
    kind_column = "Rodzaj"


class MeterExportParser(MeterReadingsParser):
    name = "odczyty_licznika"
    label = "Odczyty licznika (Data; Strefa; Wartość; Rodzaj; Status)"
    date_column = "Data"
    value_column = "Wartość"
    kind_column = "Rodzaj"

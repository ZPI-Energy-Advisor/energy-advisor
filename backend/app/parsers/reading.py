import csv
import io
import json

import pandas as pd

from app.parsers.base import FileImportError


SEPARATORS = (";", ",", "\t")
ENCODINGS = ("utf-8-sig", "windows-1250")
ZIP_SIGNATURE = b"PK\x03\x04"
ROW_ERRORS = "row_errors"


def _decode(raw: bytes) -> str:
    if raw.startswith(ZIP_SIGNATURE):
        raise FileImportError(
            400,
            "To jest plik Excel (.xlsx) albo archiwum ZIP, a nie CSV. "
            "Otwórz go w Excelu i zapisz jako „CSV (rozdzielany średnikami)”.",
        )
    if b"\x00" in raw:
        raise FileImportError(400, "Plik nie jest plikiem tekstowym CSV.")
    for encoding in ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        control_chars = sum(1 for char in text if char < " " and char not in "\r\n\t")
        if control_chars > len(text) / 100:
            raise FileImportError(400, "Plik nie jest plikiem tekstowym CSV.")
        return text
    raise FileImportError(400, "Nieobsługiwane kodowanie znaków w pliku. Zapisz plik w UTF-8 albo Windows-1250.")


def _separator(header_line: str) -> str:
    counts = {separator: header_line.count(separator) for separator in SEPARATORS}
    best = max(counts, key=counts.get)
    return best if counts[best] else ";"


def read_document(file_obj) -> dict | None:
    """Zwraca dokument JSON albo None, gdy plik nie jest JSON-em (wtedy obowiązuje ścieżka CSV).

    O formacie decyduje treść, nie rozszerzenie: JSON to plik w UTF-8, którego pierwszy znak
    (po BOM i białych znakach) to „{”.
    """
    file_obj.seek(0)
    raw = file_obj.read()
    file_obj.seek(0)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if not text.lstrip().startswith("{"):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise FileImportError(
            400, f"Niepoprawny plik JSON: {error.msg} (linia {error.lineno}, kolumna {error.colno})."
        ) from error


def read_table(file_obj) -> pd.DataFrame:
    file_obj.seek(0)
    text = _decode(file_obj.read())

    header_line = next((line for line in text.splitlines() if line.strip()), None)
    if header_line is None:
        raise FileImportError(400, "Plik jest pusty.")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_separator(header_line))
    header = None
    rows, line_numbers, row_errors = [], [], {}
    for fields in reader:
        fields = [field.strip() for field in fields]
        if not any(fields):
            continue
        if header is None:
            header = fields
            continue
        if fields == header:
            continue

        line = reader.line_num
        if len(fields) > len(header) and not any(fields[len(header):]):
            fields = fields[:len(header)]
        if len(fields) != len(header):
            row_errors[line] = f"nieprawidłowa liczba kolumn ({len(fields)} zamiast {len(header)})"
            fields = [""] * len(header)

        rows.append([field or None for field in fields])
        line_numbers.append(line)

    table = pd.DataFrame(rows, columns=header, index=line_numbers, dtype=object)
    table.attrs[ROW_ERRORS] = row_errors
    return table


YEAR_FIRST_DATE = r'^\d{4}-\d{1,2}-\d{1,2}[ T]+\d{1,2}:\d{2}'
DAY_OR_MONTH_FIRST_DATE = r'^(\d{1,2})[./-](\d{1,2})[./-]\d{4}\s+\d{1,2}:\d{2}'
EXCEL_SERIAL_DATE = r'^\d+(?:\.\d+)?$'
QUARTER_HOUR_RESOLUTION = 15
HOURLY_RESOLUTION = 60

MIDNIGHT_24 = r'(?<=\s)24:00(?=(?::00)?$)'


def parse_dates(values: pd.Series) -> pd.Series:
    """Rozpoznaje format każdej daty po jej zapisie, a nie po nazwach kolumn pliku.

    - RRRR-MM-DD (np. plik zapisany ponownie w Excelu) - zawsze rok, miesiąc, dzień,
    - DD.MM.RRRR, DD/MM/RRRR, DD-MM-RRRR - kolejność dnia i miesiąca ustalana dla całego
      pliku: jeśli gdzieś pierwsza liczba > 12, to dzień jest pierwszy; jeśli tylko druga
      liczba bywa > 12, to plik jest w układzie MM/DD; gdy nie da się tego rozstrzygnąć,
      przyjmujemy polski układ z dniem na początku,
    - liczby - numer seryjny daty z Excela.

    Wartości w nierozpoznanym formacie dostają NaT.
    """
    parsed = pd.Series(pd.NaT, index=values.index, dtype='datetime64[ns]')

    year_first = values.str.match(YEAR_FIRST_DATE)
    if year_first.any():
        parsed[year_first] = pd.to_datetime(
            values[year_first], format='mixed', yearfirst=True, dayfirst=False, errors='coerce'
        )

    day_or_month_first = values.str.match(DAY_OR_MONTH_FIRST_DATE)
    if day_or_month_first.any():
        parts = values[day_or_month_first].str.extract(DAY_OR_MONTH_FIRST_DATE).astype(int)
        month_first = not (parts[0] > 12).any() and (parts[1] > 12).any()
        parsed[day_or_month_first] = pd.to_datetime(
            values[day_or_month_first], format='mixed', dayfirst=not month_first, errors='coerce'
        )

    excel_serial = values.str.match(EXCEL_SERIAL_DATE)
    if excel_serial.any():
        parsed[excel_serial] = pd.to_datetime(
            pd.to_numeric(values[excel_serial]), unit='D', origin='1899-12-30'
        ).dt.round('min')

    return parsed


def parse_reading_ends(values: pd.Series) -> pd.Series:
    values = values.astype(str).str.strip()
    midnight_24 = values.str.contains(MIDNIGHT_24, regex=True)
    parsed = parse_dates(values.str.replace(MIDNIGHT_24, '00:00', regex=True))
    parsed[midnight_24] = parsed[midnight_24] + pd.Timedelta(days=1)
    return parsed


def detect_resolution_minutes(timestamps: pd.Series) -> int:
    steps = timestamps.drop_duplicates().sort_values().diff().dropna().dt.total_seconds() / 60
    if steps.empty:
        return HOURLY_RESOLUTION

    smallest_step = steps.min()
    if smallest_step == QUARTER_HOUR_RESOLUTION:
        return QUARTER_HOUR_RESOLUTION
    if smallest_step >= HOURLY_RESOLUTION and (steps % HOURLY_RESOLUTION == 0).all():
        return HOURLY_RESOLUTION
    raise FileImportError(
        422,
        f"Nieobsługiwana rozdzielczość danych (odstęp {smallest_step:g} min między odczytami). "
        "Obsługiwane są pliki z odczytami co 15 minut albo co godzinę.",
    )

"""Logi bez danych osobowych i tokenów.

`RedactingFilter` maskuje adresy e-mail, nagłówki `Bearer ...` i ciągi o kształcie JWT w treści
komunikatu i w tracebacku (np. IntegrityError z SQLAlchemy zawiera wartości kolumn, w tym e-mail).
Filtr działa na handlerach, bo filtry loggerów nie obejmują rekordów z loggerów potomnych.
"""

import logging
import re

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+")
JWT_PATTERN = re.compile(r"\beyJ[\w-]*\.[\w-]+\.[\w-]+")

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# Loggery uvicorna mają własne handlery i nie przekazują rekordów do roota.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def redact(text: str) -> str:
    text = JWT_PATTERN.sub("[TOKEN]", text)
    text = BEARER_PATTERN.sub("Bearer [TOKEN]", text)
    return EMAIL_PATTERN.sub("[EMAIL]", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # Błędne argumenty komunikatu zgłosi formatter handlera, filtr nie może przerwać logowania.
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def _add_filter(handler: logging.Handler) -> None:
    if not any(isinstance(existing, RedactingFilter) for existing in handler.filters):
        handler.addFilter(RedactingFilter())


def configure_logging(level: int = logging.INFO) -> None:
    """Root dostaje handler z filtrem (jeśli nie ma własnego), a filtr trafia też na handlery uvicorna."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
        root.setLevel(level)
    for handler in root.handlers:
        _add_filter(handler)
    for name in UVICORN_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            _add_filter(handler)

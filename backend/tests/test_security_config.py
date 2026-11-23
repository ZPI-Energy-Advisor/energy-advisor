import logging

import pytest

from app.config import MIN_SECRET_LENGTH, optional_secret, require_secret
from app.core.logging_config import RedactingFilter, configure_logging, redact

STRONG_SECRET = "x" * MIN_SECRET_LENGTH
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlX3dhcnRvc2M"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "must be configured"),
        ("", "must be configured"),
        ("generate_your_own_random_secret", "placeholder"),
        ("generate_your_own_random_key", "placeholder"),
        ("x" * (MIN_SECRET_LENGTH - 1), "at least"),
    ],
)
def test_require_secret_rejects_missing_placeholder_and_short(value, message):
    with pytest.raises(RuntimeError, match=message):
        require_secret("JWT_SECRET_KEY", value)


def test_require_secret_accepts_strong_secret():
    assert require_secret("JWT_SECRET_KEY", STRONG_SECRET) == STRONG_SECRET


def test_optional_secret_empty_disables_feature_and_set_one_is_validated():
    assert optional_secret("HUB_API_KEY", None) is None
    assert optional_secret("HUB_API_KEY", "") is None
    with pytest.raises(RuntimeError, match="placeholder"):
        optional_secret("HUB_API_KEY", "generate_your_own_random_key")


def test_redact_masks_email_bearer_and_jwt():
    text = redact(f"login jan.kowalski+test@example.com Authorization: Bearer abc.def-123 token={JWT}")

    assert "jan.kowalski" not in text
    assert "abc.def-123" not in text
    assert JWT not in text
    assert "[EMAIL]" in text and "Bearer [TOKEN]" in text and "token=[TOKEN]" in text


def test_redact_keeps_ordinary_messages():
    message = "Synchronizacja zakończona: status=success, rekordy=96, plik plan-2026.csv"
    assert redact(message) == message


def _record(msg, *args, exc_info=None):
    return logging.LogRecord("test", logging.WARNING, __file__, 1, msg, args, exc_info)


def test_filter_redacts_arguments_and_traceback():
    try:
        raise ValueError("Key (email)=(ala@example.com) already exists")
    except ValueError:
        import sys

        record = _record("Nie udało się zarejestrować %s", "ala@example.com", exc_info=sys.exc_info())

    assert RedactingFilter().filter(record) is True
    assert record.getMessage() == "Nie udało się zarejestrować [EMAIL]"
    assert "ala@example.com" not in record.exc_text
    assert "[EMAIL]" in record.exc_text


def test_configure_logging_attaches_filter_once_to_uvicorn_handlers():
    uvicorn_logger = logging.getLogger("uvicorn.access")
    handler = logging.StreamHandler()
    uvicorn_logger.addHandler(handler)
    try:
        configure_logging()
        configure_logging()

        assert sum(isinstance(f, RedactingFilter) for f in handler.filters) == 1
        assert all(any(isinstance(f, RedactingFilter) for f in h.filters) for h in logging.getLogger().handlers)
    finally:
        uvicorn_logger.removeHandler(handler)

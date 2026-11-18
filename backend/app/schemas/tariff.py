from datetime import date

from pydantic import BaseModel


class TariffOut(BaseModel):
    """Taryfa z profilu w nowym cenniku; `code` to klucz taryfy w kosztach plików (np. G12 albo G12-dynamic)."""

    code: str
    label: str
    name: str | None = None
    operator: str
    tariff_code: str
    distribution_group: str
    dynamic: bool
    valid_from: date
    valid_to: date

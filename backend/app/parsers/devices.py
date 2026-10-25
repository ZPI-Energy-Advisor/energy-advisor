from app.parsers.base import DocumentParser, FileImportError, ParsedEnergyFile


NOT_YET_SUPPORTED = (
    "Import plików urządzeń smart home (JSON) będzie dostępny wkrótce. "
    "Na razie wgraj dane z licznika w formacie CSV."
)


class DevicesJsonParser(DocumentParser):
    """Plik urządzeń zgodny z docs/devices-file-format.md. Pełne parsowanie powstaje w ZP-70."""

    name = "devices"
    label = "Plik urządzeń smart home (JSON)"

    def detect(self, document: dict) -> bool:
        return "devices" in document and "energy_usage" in document

    def parse(self, document: dict) -> ParsedEnergyFile:
        raise FileImportError(422, NOT_YET_SUPPORTED)

import json
import os
from pathlib import Path

from device.models import DeviceConfig



class StateFile:
    """Rejestr domu z portami na dysku: po restarcie huba urządzenia wracają na te same porty."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[int, DeviceConfig]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {item["port"]: DeviceConfig.model_validate(item["config"]) for item in data["devices"]}

    def save(self, devices: dict[int, DeviceConfig]) -> None:
        payload = {"devices": [
            {"port": port, "config": config.model_dump(by_alias=True)}
            for port, config in sorted(devices.items())
        ]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Zapis przez plik tymczasowy, żeby przerwany zapis nie zostawił uszkodzonego stanu.
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary_path, self.path)

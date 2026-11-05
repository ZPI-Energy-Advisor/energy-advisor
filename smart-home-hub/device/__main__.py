import argparse
import json
from pathlib import Path

import uvicorn

from device.api import create_app
from device.driver import DeviceDriver
from device.models import DeviceConfig, StartupConfig



def main() -> None:
    parser = argparse.ArgumentParser(description="Mikroserwis jednego urządzenia Smart Home")
    parser.add_argument("--config", type=Path, required=True, help="plik JSON z konfiguracją urządzenia")
    args = parser.parse_args()

    raw_config = json.loads(args.config.read_text(encoding="utf-8"))
    startup = StartupConfig.model_validate(raw_config)
    driver = DeviceDriver(DeviceConfig.model_validate(raw_config))

    uvicorn.run(create_app(driver), host=startup.bind_host, port=startup.port, log_level="warning")


if __name__ == "__main__":
    main()

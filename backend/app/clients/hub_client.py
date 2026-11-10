from datetime import datetime
from typing import TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from app.schemas.smart_home import (
    CommandResult,
    DeviceCommand,
    HubClock,
    HubDevice,
    HubDevicesStatus,
    RegisteredDevice,
)



API_KEY_HEADER = "X-Hub-Api-Key"
DEFAULT_TIMEOUT_SECONDS = 5.0
# Hub odpowiada na PUT /home/devices dopiero po uruchomieniu wszystkich mikroserwisów.
REGISTRY_TIMEOUT_SECONDS = 60.0
# Ponawiać można tylko żądania, których powtórzenie niczego nie zmienia. Komenda mogła dojść do huba
# mimo timeoutu, a hub nie rozpoznaje powtórzeń, więc ponowiona mogłaby się wykonać drugi raz.
RETRYABLE_METHODS = ("GET", "PUT")

ModelT = TypeVar("ModelT", bound=BaseModel)


class HubError(Exception):
    """Błąd komunikacji z hubem Smart Home. `code` pochodzi z odpowiedzi huba, gdy ją podał."""

    def __init__(self, message: str, status_code: int | None = None, code: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


class HubUnavailableError(HubError):
    """Hub nie odpowiedział (timeout, brak połączenia) albo zwrócił 5xx.

    `retryable` mówi, czy żądanie można bezpiecznie ponowić (tylko GET i PUT).
    """

    def __init__(self, message: str, status_code: int | None = None, code: str | None = None, retryable: bool = True):
        super().__init__(message, status_code=status_code, code=code, retryable=retryable)


class HubAuthError(HubError):
    """Hub odrzucił HUB_API_KEY – błąd konfiguracji, ponawianie nic nie da."""


class HubClient:
    """Klient API huba Smart Home (backend → hub). Kontrakt: docs/smart-home-api.md."""

    def __init__(self, client: httpx.Client):
        self.client = client

    @classmethod
    def create(cls, base_url: str, api_key: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> "HubClient":
        return cls(httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={API_KEY_HEADER: api_key, "Accept": "application/json"},
        ))

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def registry_payload(devices: list[HubDevice]) -> dict:
        """Treść PUT /home/devices dla rejestru `devices`."""
        return {"devices": [device.model_dump(mode="json", by_alias=True) for device in devices]}

    def put_devices(self, devices: list[HubDevice]) -> list[RegisteredDevice]:
        payload = self.registry_payload(devices)
        data = self._request("PUT", "/home/devices", json=payload, timeout=REGISTRY_TIMEOUT_SECONDS)
        return [self._parse(RegisteredDevice, item) for item in self._field(data, "devices")]

    def get_devices(self) -> HubDevicesStatus:
        return self._parse(HubDevicesStatus, self._request("GET", "/home/devices"))

    def send_command(self, device_id: str, command: DeviceCommand) -> CommandResult:
        data = self._request(
            "POST",
            f"/home/devices/{quote(device_id, safe='')}/commands",  # device_id pochodzi z pliku użytkownika
            json=command.model_dump(mode="json", exclude_none=True),
        )
        return self._parse(CommandResult, data)

    def get_clock(self) -> HubClock:
        return self._parse(HubClock, self._request("GET", "/home/clock"))

    def update_clock(self, sim_time: datetime | None = None, running: bool | None = None, speed: float | None = None) -> HubClock:
        """Zmienia podane pola zegara; pominięte zostają bez zmian."""
        payload = {"sim_time": sim_time.isoformat() if sim_time else None, "running": running, "speed": speed}
        payload = {key: value for key, value in payload.items() if value is not None}
        return self._parse(HubClock, self._request("PUT", "/home/clock", json=payload))

    def _request(self, method: str, path: str, json: dict | None = None, timeout=httpx.USE_CLIENT_DEFAULT) -> dict:
        retryable = method in RETRYABLE_METHODS
        try:
            response = self.client.request(method, path, json=json, timeout=timeout)
        except httpx.TimeoutException as e:
            raise HubUnavailableError(f"Hub nie odpowiedział w czasie ({method} {path})", retryable=retryable) from e
        except httpx.HTTPError as e:
            raise HubUnavailableError(f"Błąd połączenia z hubem ({method} {path}): {e}", retryable=retryable) from e

        if response.is_success:
            try:
                data = response.json()
            except ValueError as e:
                raise HubError(f"Hub zwrócił niepoprawny JSON ({method} {path})") from e
            if not isinstance(data, dict):
                raise HubError(f"Nieoczekiwany format odpowiedzi huba ({method} {path})")
            return data

        detail, code = self._error_detail(response)
        message = f"Hub zwrócił HTTP {response.status_code} ({method} {path}): {detail}"
        if response.status_code in (401, 403):
            raise HubAuthError(message, status_code=response.status_code, code=code)
        if response.status_code >= 500:
            raise HubUnavailableError(message, status_code=response.status_code, code=code, retryable=retryable)
        raise HubError(message, status_code=response.status_code, code=code)

    @staticmethod
    def _error_detail(response: httpx.Response) -> tuple[str, str | None]:
        try:
            body = response.json()
        except ValueError:
            return response.text or response.reason_phrase, None
        if isinstance(body, dict):
            return str(body.get("detail", body)), body.get("code")
        return str(body), None

    @staticmethod
    def _field(data: dict, name: str) -> list:
        value = data.get(name)
        if not isinstance(value, list):
            raise HubError(f"Odpowiedź huba nie zawiera listy {name!r}")
        return value

    @staticmethod
    def _parse(model: type[ModelT], data) -> ModelT:
        try:
            return model.model_validate(data)
        except ValidationError as e:
            raise HubError(f"Odpowiedź huba niezgodna z kontraktem: {e}") from e

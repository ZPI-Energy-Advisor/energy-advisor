import asyncio
import json
import logging
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from device.driver import EDITABLE_FIELDS
from device.models import DeviceConfig
from hub.clock import SimClock
from hub.config import HubSettings
from hub.models import ClockUpdate, DeviceCommand
from hub.state import StateFile
from hub.webhook import EventPublisher



logger = logging.getLogger(__name__)

HUB_DIR = Path(__file__).resolve().parents[1]
DEVICE_REQUEST_TIMEOUT_SECONDS = 3.0
HEALTH_POLL_SECONDS = 0.05
STOP_TIMEOUT_SECONDS = 5.0
# Ile czasu przy zamykaniu huba dostaje ostatnia wysyłka zdarzeń do backendu.
FLUSH_TIMEOUT_SECONDS = 5.0

UNREACHABLE = "unreachable"
ERROR = "error"
RESTART_LIMIT_CODE = "restart_limit_exceeded"


class HubError(Exception):
    """Błąd kontraktu: status HTTP, kod maszynowy i opis dla człowieka."""

    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


@dataclass
class ManagedDevice:
    config: DeviceConfig
    port: int
    process: subprocess.Popen | None = None
    restarts: int = 0
    failed: bool = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@dataclass
class ScheduledCommand:
    device_id: str
    command_id: str
    command: DeviceCommand


class DeviceSupervisor:
    """Stawia, restartuje i zatrzymuje mikroserwisy urządzeń. Kontrakt: docs/smart-home-api.md."""

    def __init__(self, settings: HubSettings, publisher: EventPublisher | None = None):
        self.settings = settings
        # Zdarzenia z ticków i health-checku czekają tu na webhook do backendu.
        self.publisher = publisher or EventPublisher(settings)
        self.devices: dict[str, ManagedDevice] = {}
        self._state = StateFile(settings.state_dir / "state.json")
        self._lock = asyncio.Lock()  # Rekoncyliacja i health-check nie mogą restartować naraz.
        self._client: httpx.AsyncClient | None = None
        self.clock = SimClock()
        # Osobna blokada: tick nie może czekać na restart niedziałającego urządzenia.
        self._clock_lock = asyncio.Lock()
        self._scheduled: list[ScheduledCommand] = []

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=DEVICE_REQUEST_TIMEOUT_SECONDS, trust_env=False)
        for port, config in self._state.load().items():
            self.devices[config.device_id] = ManagedDevice(config=config, port=port)
        await asyncio.gather(*(self._start_device(device) for device in self.devices.values()))

    async def stop(self) -> None:
        await asyncio.gather(*(self._stop_process(device) for device in self.devices.values()))
        await self._client.aclose()
        # Zegar już stoi, więc nowych zdarzeń nie będzie; reszta kolejki ma jedną szansę dotrzeć do backendu.
        try:
            await asyncio.wait_for(self.publisher.flush(), FLUSH_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning("Przy zamykaniu huba nie wysłano %d zdarzeń", len(self.publisher.pending))
        await self.publisher.close()

    async def run_webhook_loop(self) -> None:
        await self.publisher.run()

    async def apply_registry(self, configs: list[DeviceConfig]) -> list[dict]:
        async with self._lock:
            requested = {config.device_id: config for config in configs}
            removed = [device for device_id, device in self.devices.items() if device_id not in requested]
            added = [config for device_id, config in requested.items() if device_id not in self.devices]
            # Sprawdzone przed zmianami: przy braku portów działające urządzenia zostają bez zmian.
            kept_ports = {device.port for device in self.devices.values()} - {device.port for device in removed}
            ports = self._allocate_ports(len(added), kept_ports)

            await asyncio.gather(*(self._stop_process(device) for device in removed))
            for device in removed:
                del self.devices[device.config.device_id]
            self._scheduled = [item for item in self._scheduled if item.device_id in self.devices]

            tasks = [
                self._apply_change(self.devices[device_id], config)
                for device_id, config in requested.items()
                if device_id in self.devices
            ]
            for config, port in zip(added, ports):
                device = ManagedDevice(config=config, port=port)
                self.devices[config.device_id] = device
                tasks.append(self._start_device(device))
            await asyncio.gather(*tasks)

            self._save_state()

            registered = [self.devices[config.device_id] for config in configs]
            statuses = await asyncio.gather(*(self._read_status(device) for device in registered))
            return [
                {"device_id": device.config.device_id, "port": device.port, "state": status["state"]}
                for device, status in zip(registered, statuses)
            ]

    async def list_devices(self) -> list[dict]:
        devices = list(self.devices.values())
        statuses = await asyncio.gather(*(self._read_status(device) for device in devices))
        return [
            {**status, "device_name": device.config.device_name, "port": device.port}
            for device, status in zip(devices, statuses)
        ]

    async def send_command(self, device_id: str, command: DeviceCommand) -> dict:
        device = self.devices.get(device_id)
        if device is None:
            raise HubError(404, "device_not_found", f"Nie ma urządzenia {device_id!r} w rejestrze")
        command_id = f"cmd_{uuid.uuid4().hex[:12]}"
        # Pod blokadą zegara: tick w trakcie przesuwa urządzeniom czas na kolejny kwadrans, więc komenda „teraz”
        # wysłana w jego trakcie zaczęłaby się kwadrans później, a decyzja „teraz czy później” opierałaby się na
        # czasie, który zaraz się zmieni.
        async with self._clock_lock:
            if command.start_at is not None and command.start_at < self.clock.sim_time:
                raise HubError(422, "start_at_in_past", "start_at jest wcześniejszy niż czas symulacji")
            if command.start_at is not None and command.start_at > self.clock.sim_time:
                self._require_program(device, command.program_id)
                self._scheduled.append(ScheduledCommand(device_id, command_id, command))
                status = None
            else:
                status = await self._forward(device, self._command_path(command), payload={"command_id": command_id})
        if status is None:
            status = await self._read_status(device)
            result = "scheduled"
        else:
            result = "accepted"
        return {"command_id": command_id, "device_id": device_id, "status": result, "state": status["state"]}

    async def update_clock(self, update: ClockUpdate) -> dict:
        async with self._clock_lock:
            # Ponowiony PUT z tym samym czasem niczego nie zmienia, a HubClient ponawia PUT-y.
            if update.sim_time is not None and not self.clock.is_at(update.sim_time):
                if self.clock.running:
                    raise HubError(409, "clock_running", "Czas można ustawić tylko przy zatrzymanym zegarze")
                await self._start_new_simulation(update.sim_time)
            self.clock.configure(update.running, update.speed)
            return self.clock.state()

    async def tick(self) -> None:
        async with self._clock_lock:
            await self._tick()

    async def run_clock_loop(self) -> None:
        while True:
            await self.clock.wait_for_step()
            async with self._clock_lock:
                if self.clock.running:  # Zegar mógł stanąć w trakcie czekania na blokadę.
                    started = time.monotonic()
                    try:
                        await self._tick()
                    except Exception:
                        logger.exception("Tick nie powiódł się, zegar ponowi ten kwadrans")
                    self.clock.spend(time.monotonic() - started)

    async def check_health(self) -> None:
        async with self._lock:
            checked = [device for device in self.devices.values() if not device.failed]
            await asyncio.gather(*(self._check_device(device) for device in checked))

    async def run_health_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.health_interval_seconds)
            await self.check_health()

    async def _tick(self) -> None:
        sim_time = self.clock.next_time
        devices = [device for device in self.devices.values() if not device.failed]
        tick_events = await asyncio.gather(*(self._tick_device(device, sim_time) for device in devices))
        self.clock.advance()

        # Po ticku, bo akcja zaczyna się w czasie ostatniego ticka urządzenia.
        due = [item for item in self._scheduled if item.command.start_at <= sim_time]
        self._scheduled = [item for item in self._scheduled if item.command.start_at > sim_time]
        command_events = await asyncio.gather(*(
            self._run_scheduled(self.devices[item.device_id], item, sim_time) for item in due
        ))
        # Jedna partia na tick: backend dostaje kwadrans w całości, a nie po jednym urządzeniu.
        self._publish([event for events in (*tick_events, *command_events) for event in events])

    async def _tick_device(self, device: ManagedDevice, sim_time: datetime) -> list[dict]:
        try:
            result = await self._forward(device, "/tick", payload={"sim_time": sim_time.isoformat()})
        except HubError as e:
            return [self._device_error(device, sim_time, e.code, e.detail)]
        return self._tick_events(device, sim_time, result)

    async def _run_scheduled(self, device: ManagedDevice, item: ScheduledCommand, sim_time: datetime) -> list[dict]:
        try:
            await self._forward(device, self._command_path(item.command), payload={"command_id": item.command_id})
        except HubError as e:
            return [self._device_error(device, sim_time, e.code, e.detail)]
        return []

    @staticmethod
    def _tick_events(device: ManagedDevice, sim_time: datetime, result: dict) -> list[dict]:
        """Zdarzenia urządzenia z odpowiedzi ticka i energy_report z energii kroku."""
        device_id = device.config.device_id
        events = [{**event, "device_id": device_id} for event in result.get("events", [])]
        energy_kwh = result.get("energy_kwh") or 0.0
        # Przedział od urządzenia, a nie od zegara: po pominiętym ticku krok urządzenia jest dłuższy niż kwadrans.
        if energy_kwh and result.get("interval_start"):
            events.append({
                "type": "energy_report",
                "device_id": device_id,
                "sim_time": sim_time.isoformat(),
                "data": {"interval_start": result["interval_start"], "energy_kwh": energy_kwh},
            })
        return events

    @staticmethod
    def _device_error(device: ManagedDevice, sim_time: datetime, code: str, message: str) -> dict:
        logger.warning("Błąd urządzenia %s: %s", device.config.device_id, message)
        return {
            "type": "device_error",
            "device_id": device.config.device_id,
            "sim_time": sim_time.isoformat(),
            "data": {"code": code, "message": message},
        }

    def _publish(self, events: list[dict]) -> None:
        self.publisher.publish(self.clock.simulation_id, events)

    async def _start_new_simulation(self, sim_time: datetime) -> None:
        devices = [device for device in self.devices.values() if not device.failed]
        results = await asyncio.gather(*(self._reset_device(device) for device in devices))
        not_reset = [device.config.device_id for device, reset in zip(devices, results) if not reset]
        if not_reset:
            raise HubError(502, "device_unreachable", f"Urządzenia bez resetu: {', '.join(not_reset)}")
        self.clock.set_time(sim_time)
        self._scheduled.clear()
        await asyncio.gather(*(self._sync_time(device) for device in devices))

    async def _reset_device(self, device: ManagedDevice) -> bool:
        try:
            await self._forward(device, "/reset")
        except HubError as e:
            logger.warning("Urządzenie %s bez resetu: %s", device.config.device_id, e.detail)
            return False
        return True

    async def _sync_time(self, device: ManagedDevice) -> None:
        """Tick z bieżącym czasem: dzięki niemu komenda zacznie się teraz, a nie przy kolejnym kroku."""
        sim_time = self.clock.sim_time
        try:
            result = await self._forward(device, "/tick", payload={"sim_time": sim_time.isoformat()})
        except HubError as e:
            logger.warning("Urządzenie %s bez czasu symulacji: %s", device.config.device_id, e.detail)
            return
        self._publish(self._tick_events(device, sim_time, result))

    def _allocate_ports(self, count: int, used_ports: set[int]) -> list[int]:
        pool = range(self.settings.first_port, self.settings.last_port + 1)
        free_ports = [port for port in pool if port not in used_ports]
        if count > len(free_ports):
            raise HubError(409, "port_pool_exhausted", f"Brak wolnych portów dla {count} nowych urządzeń")
        return free_ports[:count]

    async def _apply_change(self, device: ManagedDevice, config: DeviceConfig) -> None:
        changed = device.config != config
        requires_restart = (
            device.config.model_dump(exclude=EDITABLE_FIELDS) != config.model_dump(exclude=EDITABLE_FIELDS)
        )
        device.config = config
        if not changed:
            return
        if requires_restart or not await self._update_running_config(device):
            device.restarts = 0
            device.failed = False
            await self._start_device(device)

    async def _update_running_config(self, device: ManagedDevice) -> bool:
        changes = {"device_name": device.config.device_name, "device_category": device.config.device_category}
        try:
            response = await self._client.put(f"{device.url}/config", json=changes)
        except httpx.HTTPError:
            return False
        return response.is_success

    async def _check_device(self, device: ManagedDevice) -> None:
        if device.process.poll() is None and await self._is_healthy(device):
            device.restarts = 0
            return
        if device.restarts >= self.settings.max_restarts:
            logger.error("Urządzenie %s nie wstało po %d restartach", device.config.device_id, device.restarts)
            device.failed = True
            await self._stop_process(device)
            self._publish([self._device_error(
                device, self.clock.sim_time, RESTART_LIMIT_CODE,
                f"Urządzenie nie wstało po {device.restarts} restartach",
            )])
            return
        device.restarts += 1
        logger.warning("Restart urządzenia %s (próba %d)", device.config.device_id, device.restarts)
        await self._start_device(device)

    async def _start_device(self, device: ManagedDevice) -> None:
        await self._stop_process(device)
        config_path = self._write_device_config(device)
        device.process = subprocess.Popen(
            [sys.executable, "-m", "device", "--config", str(config_path)],
            cwd=HUB_DIR,
        )
        if not await self._wait_until_healthy(device):
            logger.warning("Urządzenie %s nie odpowiada po starcie", device.config.device_id)
            return
        await self._sync_time(device)

    async def _stop_process(self, device: ManagedDevice) -> None:
        process, device.process = device.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait)

    def _write_device_config(self, device: ManagedDevice) -> Path:
        # Nazwa z portu, a nie z device_id, bo device_id pochodzi z pliku użytkownika.
        path = self.settings.state_dir / "devices" / f"{device.port}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **device.config.model_dump(by_alias=True),
            "port": device.port,
            "bind_host": self.settings.device_bind_host,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    async def _wait_until_healthy(self, device: ManagedDevice) -> bool:
        deadline = time.monotonic() + self.settings.device_start_timeout_seconds
        while time.monotonic() < deadline:
            if device.process.poll() is not None:
                return False
            if await self._is_healthy(device):
                return True
            await asyncio.sleep(HEALTH_POLL_SECONDS)
        return False

    async def _is_healthy(self, device: ManagedDevice) -> bool:
        try:
            response = await self._client.get(f"{device.url}/health")
        except httpx.HTTPError:
            return False
        return response.is_success and response.json().get("device_id") == device.config.device_id

    async def _read_status(self, device: ManagedDevice) -> dict:
        if device.failed:
            return self._status_without_readings(device, ERROR)
        try:
            return await self._forward(device, "/status", method="GET")
        except HubError:
            return self._status_without_readings(device, UNREACHABLE)

    async def _forward(
        self, device: ManagedDevice, path: str, method: str = "POST", payload: dict | None = None,
    ) -> dict:
        try:
            response = await self._client.request(method, f"{device.url}{path}", json=payload)
        except httpx.HTTPError as e:
            raise HubError(502, "device_unreachable", f"Brak odpowiedzi urządzenia: {e}") from e
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise HubError(502, "device_unreachable", f"Urządzenie zwróciło HTTP {response.status_code} bez obiektu JSON")
        if response.is_success:
            return body
        raise HubError(response.status_code, body.get("code"), body.get("detail"))

    def _save_state(self) -> None:
        self._state.save({device.port: device.config for device in self.devices.values()})

    @staticmethod
    def _require_program(device: ManagedDevice, program_id: str) -> None:
        if not any(program.program_id == program_id for program in device.config.programs):
            raise HubError(404, "program_not_found", f"Urządzenie nie ma programu {program_id!r}")

    @staticmethod
    def _command_path(command: DeviceCommand) -> str:
        if command.command == "start_program":
            return f"/programs/{quote(command.program_id, safe='')}/start"
        return f"/{command.command}"

    @staticmethod
    def _status_without_readings(device: ManagedDevice, state: str) -> dict:
        return {
            "device_id": device.config.device_id,
            "state": state,
            "program_id": None,
            "program_started_at": None,
            "program_ends_at": None,
            "power_kw": None,
            "energy_kwh": None,
        }

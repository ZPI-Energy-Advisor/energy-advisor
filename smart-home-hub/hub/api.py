import asyncio
import contextlib
import secrets
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from hub.config import HubSettings
from hub.models import ClockUpdate, DeviceCommand, RegistryRequest
from hub.supervisor import DeviceSupervisor, HubError



def create_app(settings: HubSettings | None = None) -> FastAPI:
    """API huba dla backendu. Kontrakt: docs/smart-home-api.md, część „Backend → hub”."""
    settings = settings or HubSettings.from_env()
    supervisor = DeviceSupervisor(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await supervisor.start()
        loops = [
            asyncio.create_task(supervisor.run_health_loop()),
            asyncio.create_task(supervisor.run_clock_loop()),
        ]
        yield
        for loop in loops:
            loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop
        await supervisor.stop()

    def verify_api_key(x_hub_api_key: str | None = Header(default=None)) -> None:
        provided = (x_hub_api_key or "").encode()
        if not secrets.compare_digest(provided, settings.api_key.encode()):
            raise HubError(401, "invalid_api_key", "Brak albo błędny X-Hub-Api-Key")

    app = FastAPI(title="Smart Home Hub", lifespan=lifespan)
    app.state.supervisor = supervisor
    router = APIRouter(prefix="/home", dependencies=[Depends(verify_api_key)])

    @app.exception_handler(HubError)
    async def handle_hub_error(request: Request, error: HubError):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail, "code": error.code})

    @app.exception_handler(RequestValidationError)
    async def handle_invalid_request(request: Request, error: RequestValidationError):
        # value_error pochodzi z walidatorów modeli: dane są czytelne, ale łamią reguły kontraktu.
        if any(item["type"] == "value_error" for item in error.errors()):
            return JSONResponse(
                status_code=422,
                content={"detail": "Dane łamią reguły kontraktu", "code": "validation_error"},
            )
        return JSONResponse(
            status_code=400,
            content={"detail": "Niepoprawne żądanie", "code": "invalid_request"},
        )

    @router.put("/devices")
    async def put_devices(request: RegistryRequest):
        return {"devices": await supervisor.apply_registry(request.devices)}

    @router.get("/devices")
    async def get_devices():
        devices = await supervisor.list_devices()
        return {"sim_time": supervisor.clock.state()["sim_time"], "devices": devices}

    @router.post("/devices/{device_id}/commands", status_code=202)
    async def send_command(device_id: str, command: DeviceCommand):
        return await supervisor.send_command(device_id, command)

    @router.get("/clock")
    async def get_clock():
        return supervisor.clock.state()

    @router.put("/clock")
    async def put_clock(update: ClockUpdate):
        return await supervisor.update_clock(update)

    app.include_router(router)
    return app

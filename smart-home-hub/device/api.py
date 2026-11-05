from fastapi import Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from device.driver import DeviceDriver, DeviceError
from device.models import TickRequest



def create_app(driver: DeviceDriver) -> FastAPI:
    """API jednego urządzenia.
    Endpointy są async, żeby żądania obsługiwała jedna pętla: stan sterownika nie ma blokad.
    """
    app = FastAPI(title=f"Urządzenie {driver.config.device_id}")

    @app.exception_handler(DeviceError)
    async def handle_device_error(request: Request, error: DeviceError):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail, "code": error.code})

    @app.exception_handler(RequestValidationError)
    async def handle_invalid_request(request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Niepoprawne żądanie", "code": "invalid_request"},
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "device_id": driver.config.device_id}

    @app.get("/config")
    async def get_config():
        return _config_body(driver)

    @app.put("/config")
    async def put_config(changes: dict = Body(...)):
        driver.update_config(changes)
        return _config_body(driver)

    @app.get("/status")
    async def status():
        return driver.status()

    @app.post("/on")
    async def turn_on():
        driver.turn_on()
        return driver.status()

    @app.post("/off")
    async def turn_off():
        driver.turn_off()
        return driver.status()

    @app.post("/programs/{program_id}/start")
    async def start_program(program_id: str):
        driver.start_program(program_id)
        return driver.status()

    @app.get("/energy")
    async def energy():
        return driver.energy()

    @app.post("/tick")
    async def tick(request: TickRequest):
        return driver.tick(request.sim_time)

    return app


def _config_body(driver: DeviceDriver) -> dict:
    return driver.config.model_dump(by_alias=True, exclude_none=True)

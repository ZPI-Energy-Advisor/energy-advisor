from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse



class ContractError(Exception):
    """Błąd w formacie kontraktu Smart Home: `{"detail": ..., "code": ...}` """

    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ContractError)
    async def handle_contract_error(request: Request, error: ContractError):
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail, "code": error.code})

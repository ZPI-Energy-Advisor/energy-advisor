from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.upload import router as upload_router
from app.api.v1.results import router as results_router
from app.api.v1.energy_files import router as energy_files_router
from app.api.v1.dynamic_prices import router as dynamic_prices_router
from app.api.v1.tariffs import router as tariffs_router
from app.api.v1.users import router as users_router
from app.api.v1.home import router as home_router
from app.config import CORS_ORIGINS
from app.core.smart_home_factory import build_app_hub_client



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Zasoby na czas życia aplikacji: tworzone przed pierwszym żądaniem, zamykane przy wyłączeniu."""
    hub_client = build_app_hub_client()
    app.state.hub_client = hub_client
    try:
        yield
    finally:
        # Po wyłączeniu nikt nie może dostać zamkniętego klienta.
        app.state.hub_client = None
        if hub_client is not None:
            hub_client.close()


app = FastAPI(title="Energy Advisor API", lifespan=lifespan)
# Stan bez lifespanu (np. TestClient użyty bez `with`): Smart Home wyłączony.
app.state.hub_client = None

api_router = APIRouter(prefix="/api")
v1_router = APIRouter(prefix="/v1")

v1_router.include_router(auth_router)
v1_router.include_router(upload_router)
v1_router.include_router(results_router)
v1_router.include_router(energy_files_router)
v1_router.include_router(dynamic_prices_router)
v1_router.include_router(tariffs_router)
v1_router.include_router(users_router)
v1_router.include_router(home_router)
api_router.include_router(v1_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

@api_router.get("/health", tags=["Health Check"])
def get_api_health():
    return {"message": "Energy Advisor API works fine!"}

app.include_router(api_router)
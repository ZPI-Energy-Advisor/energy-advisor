from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.deps import get_authenticated_user, get_pv_forecast_service, get_user_service
from app.config import RATE_LIMIT_WEATHER
from app.core.rate_limit import limiter
from app.models.User import User
from app.schemas.pv_forecast import PvCalibrationOut, PvForecastQuarter, PvForecastResponse
from app.services.pv_forecast import NoPvInstallationError, PvForecastService, PvForecastUnavailableError
from app.services.user_service import UserService
from app.services.weather_service import EARLIEST_DAY

router = APIRouter(prefix="/pv", tags=["PV"])


@router.get("/forecast", response_model=PvForecastResponse)
@limiter.limit(RATE_LIMIT_WEATHER)
def get_pv_forecast(
    request: Request,
    day: date | None = Query(default=None, alias="date", description="Doba lokalna; domyślnie jutro"),
    user: User = Depends(get_authenticated_user),
    users: UserService = Depends(get_user_service),
    service: PvForecastService = Depends(get_pv_forecast_service),
):
    latest = service.weather.latest_day()
    day = day or service.weather.today() + timedelta(days=1)
    if not EARLIEST_DAY <= day <= latest:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Prognozę PV podajemy od {EARLIEST_DAY.isoformat()} do {latest.isoformat()}.",
        )
    profile = users.get_profile(user)
    try:
        forecast = service.forecast(user.id, profile, day)
    except NoPvInstallationError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except PvForecastUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nie ma teraz pogody do prognozy PV. Spróbuj za kilka minut.",
        )
    calibration = forecast.calibration
    return PvForecastResponse(
        date=day,
        total_kwh=forecast.total_kwh,
        complete=forecast.complete,
        basis=forecast.basis,
        calibration=PvCalibrationOut(
            coefficient=calibration.coefficient, source=calibration.source, days=calibration.days, mape=calibration.mape
        ),
        inverter_kw=forecast.inverter_kw,
        estimated_installation=forecast.estimated_installation,
        approximate_location=forecast.approximate_location,
        weather_fetched_at=forecast.weather_fetched_at,
        notes=forecast.notes,
        intervals=[PvForecastQuarter(start=q.start, kwh=q.kwh, basis=q.basis) for q in forecast.quarters],
    )

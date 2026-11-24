from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.deps import get_authenticated_user, get_user_service, get_weather_service
from app.config import RATE_LIMIT_WEATHER
from app.core.rate_limit import limiter
from app.models.User import User
from app.schemas.weather import WeatherDayResponse, WeatherInterval, WeatherPlane
from app.services.user_service import UserService
from app.services.weather_service import EARLIEST_DAY, Cell, WeatherService, WeatherUnavailableError, planes_of

router = APIRouter(prefix="/weather", tags=["Weather"])


@router.get("/forecast", response_model=WeatherDayResponse)
@limiter.limit(RATE_LIMIT_WEATHER)
def get_weather(
    request: Request,
    day: date | None = Query(default=None, alias="date", description="Doba lokalna; domyślnie dziś"),
    user: User = Depends(get_authenticated_user),
    users: UserService = Depends(get_user_service),
    weather: WeatherService = Depends(get_weather_service),
):
    day = day or weather.today()
    if not EARLIEST_DAY <= day <= weather.latest_day():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Pogodę podajemy od {EARLIEST_DAY.isoformat()} do {weather.latest_day().isoformat()}.",
        )
    profile = users.get_profile(user)
    location = profile.base_info.location
    if location is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profil nie ma lokalizacji domu.")
    try:
        result = weather.day(Cell.of(location), day, planes_of(profile))
    except WeatherUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nie udało się teraz pobrać pogody. Spróbuj za kilka minut.",
        )
    return WeatherDayResponse(
        date=day,
        latitude=float(result.cell.latitude),
        longitude=float(result.cell.longitude),
        location_approximate=location.approximate,
        planes=[WeatherPlane(tilt=plane.tilt, azimuth=plane.azimuth) for plane in result.planes],
        fetched_at=result.fetched_at,
        complete=result.complete,
        intervals=[WeatherInterval(**vars(quarter)) for quarter in result.quarters],
    )

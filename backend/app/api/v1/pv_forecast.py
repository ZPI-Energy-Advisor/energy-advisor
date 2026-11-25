from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.deps import get_authenticated_user, get_pv_forecast_service, get_pv_insights_service, get_user_service
from app.config import RATE_LIMIT_PV_SCREEN, RATE_LIMIT_WEATHER
from app.core.rate_limit import limiter
from app.models.User import User
from app.schemas.pv_forecast import (
    PvAccuracyDayOut,
    PvAccuracyResponse,
    PvArrayOut,
    PvBalanceOut,
    PvCalibrationOut,
    PvDayResponse,
    PvDaySummaryOut,
    PvForecastQuarter,
    PvForecastResponse,
    PvInstallationOut,
    PvIntervalOut,
    PvOverviewResponse,
    PvTypicalOut,
    PvValueOut,
)
from app.services.pv_forecast import NoPvInstallationError, PvForecastService, PvForecastUnavailableError
from app.services.pv_insights import PvInsightsService
from app.services.user_service import UserService
from app.services.weather_service import EARLIEST_DAY

router = APIRouter(prefix="/pv", tags=["PV"])


def _calibration_out(calibration) -> PvCalibrationOut:
    return PvCalibrationOut(
        coefficient=calibration.coefficient, source=calibration.source, days=calibration.days, mape=calibration.mape
    )


def _check_day(day: date, latest: date) -> None:
    if not EARLIEST_DAY <= day <= latest:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Dane PV podajemy od {EARLIEST_DAY.isoformat()} do {latest.isoformat()}.",
        )


@router.get("/forecast", response_model=PvForecastResponse)
@limiter.limit(RATE_LIMIT_WEATHER)
def get_pv_forecast(
    request: Request,
    day: date | None = Query(default=None, alias="date", description="Doba lokalna; domyślnie jutro"),
    user: User = Depends(get_authenticated_user),
    users: UserService = Depends(get_user_service),
    service: PvForecastService = Depends(get_pv_forecast_service),
):
    day = day or service.weather.today() + timedelta(days=1)
    _check_day(day, service.weather.latest_day())
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
    return PvForecastResponse(
        date=day,
        total_kwh=forecast.total_kwh,
        complete=forecast.complete,
        basis=forecast.basis,
        calibration=_calibration_out(forecast.calibration),
        inverter_kw=forecast.inverter_kw,
        estimated_installation=forecast.estimated_installation,
        approximate_location=forecast.approximate_location,
        weather_fetched_at=forecast.weather_fetched_at,
        notes=forecast.notes,
        intervals=[PvForecastQuarter(start=q.start, kwh=q.kwh, basis=q.basis) for q in forecast.quarters],
    )


def _setup(service: PvInsightsService, user: User, profile):
    try:
        return service.setup(user.id, profile)
    except NoPvInstallationError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except PvForecastUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.get("/overview", response_model=PvOverviewResponse)
@limiter.limit(RATE_LIMIT_PV_SCREEN)
def get_pv_overview(
    request: Request,
    user: User = Depends(get_authenticated_user),
    users: UserService = Depends(get_user_service),
    service: PvInsightsService = Depends(get_pv_insights_service),
):
    profile = users.get_profile(user)
    setup = _setup(service, user, profile)
    installation = setup.installation
    pv = profile.pv_config
    location = profile.base_info.location
    first_data_day, last_data_day = service.data_range(user.id)
    return PvOverviewResponse(
        installation=PvInstallationOut(
            total_kwp=installation.total_kwp,
            arrays=[PvArrayOut(kwp=a.power_kwp, tilt=a.tilt, azimuth=a.azimuth) for a in installation.arrays],
            inverter_kw=setup.inverter_kw,
            estimated=installation.estimated,
            settlement=pv.mode,
            price_type=pv.type_of_price.value if pv.mode == "net_billing" else None,
            k_factor=pv.effective_k_factor if pv.mode == "net_metering" else None,
        ),
        location_label=location.label if location else None,
        approximate_location=bool(location and location.approximate),
        calibration=_calibration_out(setup.calibration),
        days=[
            PvDaySummaryOut(
                date=summary.day,
                available=summary.available,
                total_kwh=summary.total_kwh,
                cloud_cover_pct=summary.cloud_cover_pct,
                temperature_min_c=summary.temperature_min_c,
                temperature_max_c=summary.temperature_max_c,
                basis=summary.basis,
                complete=summary.complete,
            )
            for summary in service.days(user.id, profile)
        ],
        first_data_day=first_data_day,
        last_data_day=last_data_day,
        today=service.weather.today(),
        latest_day=service.weather.latest_day(),
    )


@router.get("/day", response_model=PvDayResponse)
@limiter.limit(RATE_LIMIT_PV_SCREEN)
def get_pv_day(
    request: Request,
    day: date | None = Query(default=None, alias="date", description="Doba lokalna; domyślnie dziś"),
    user: User = Depends(get_authenticated_user),
    users: UserService = Depends(get_user_service),
    service: PvInsightsService = Depends(get_pv_insights_service),
):
    day = day or service.weather.today()
    _check_day(day, service.weather.latest_day())
    profile = users.get_profile(user)
    setup = _setup(service, user, profile)
    try:
        detail = service.day(user.id, profile, setup, day)
    except PvForecastUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nie ma pogody ani produkcji z pliku na ten dzień. Spróbuj za kilka minut albo wybierz inny dzień.",
        )
    balance = detail.balance
    return PvDayResponse(
        date=detail.day,
        kind=detail.kind,
        model_kwh=detail.model_kwh,
        actual_kwh=detail.actual_kwh,
        consumption_kwh=detail.consumption_kwh,
        consumption_source=detail.consumption_source,
        weather_source=detail.weather_source,
        weather_fetched_at=detail.weather_fetched_at,
        basis=detail.basis,
        balance=PvBalanceOut(
            production_kwh=balance.production_kwh,
            consumption_kwh=balance.consumption_kwh,
            self_kwh=balance.self_kwh,
            export_kwh=balance.export_kwh,
            import_kwh=balance.import_kwh,
            value=PvValueOut(**vars(balance.value)) if balance.value else None,
        ) if balance else None,
        typical=PvTypicalOut(
            days=detail.typical.days,
            first_day=detail.typical.first_day,
            last_day=detail.typical.last_day,
            kind=detail.typical.kind,
        ) if detail.typical else None,
        notes=detail.notes,
        intervals=[PvIntervalOut(**vars(interval)) for interval in detail.intervals],
    )


@router.get("/accuracy", response_model=PvAccuracyResponse)
@limiter.limit(RATE_LIMIT_PV_SCREEN)
def get_pv_accuracy(
    request: Request,
    user: User = Depends(get_authenticated_user),
    users: UserService = Depends(get_user_service),
    service: PvInsightsService = Depends(get_pv_insights_service),
):
    profile = users.get_profile(user)
    setup = _setup(service, user, profile)
    rows, days_without_weather = service.forecasts.accuracy(user.id, setup)
    return PvAccuracyResponse(
        calibration=_calibration_out(setup.calibration),
        days=[PvAccuracyDayOut(date=day, actual_kwh=actual, model_kwh=model) for day, actual, model in rows],
        days_without_weather=days_without_weather,
    )

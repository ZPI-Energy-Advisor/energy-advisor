from fastapi import APIRouter, Depends

from app.api.v1.deps import get_auth_service
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginLocalRequest,
    RefreshTokenRequest,
    RegisterLocalRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService



router = APIRouter(
    prefix="/auth", 
    tags=["Authentication"]
)


@router.post("/google", response_model=TokenResponse)
def authenticate_google(
    payload: GoogleAuthRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return service.authenticate_google_user(payload.google_code)


@router.post("/register", response_model=TokenResponse)
def register_local(
    payload: RegisterLocalRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return service.register_local_user(payload.email, payload.password)


@router.post("/login", response_model=TokenResponse)
def login_local(
    payload: LoginLocalRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return service.login_local_user(payload.email, payload.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    payload: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return service.refresh_tokens(payload.refresh_token)


@router.post("/logout", status_code=204)
def logout(
    payload: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
) -> None:
    service.invalidate_token(payload.refresh_token)

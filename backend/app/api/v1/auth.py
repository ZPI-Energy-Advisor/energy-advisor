from fastapi import APIRouter, Depends

from app.api.v1.deps import get_auth_service
from app.schemas.auth import GoogleAuthRequest, LoginLocalRequest, RegisterLocalRequest
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/google")
async def google_auth(payload: GoogleAuthRequest, service: AuthService = Depends(get_auth_service)):
    google_data = await service.fetch_google_user_data(payload.id_token)
    user = service.authenticate_google_user(google_data["email"], google_data["sub"])
    return {"status": "authenticated", "user": service.serialize_user(user)}
    
@router.post("/register")
def register_local(payload: RegisterLocalRequest, service: AuthService = Depends(get_auth_service)):
    user = service.register_local_user(payload.email, payload.password)
    return {"status": "registered", "user": service.serialize_user(user)}
    
@router.post("/login")
def login_local(payload: LoginLocalRequest, service: AuthService = Depends(get_auth_service)):
    user = service.login_local_user(payload.email, payload.password)
    return {"status": "authenticated", "user": service.serialize_user(user)}
    


from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import httpx
import re
from pydantic import BaseModel, field_validator
from passlib.context import CryptContext

from app.database import get_db
from app.models.models import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

class GoogleAuthRequest(BaseModel):
    id_token: str

@router.post("/google")
async def google_auth(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    token = payload.id_token
    
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={token}")
        
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Niepoprawny lub wygasły token Google OAuth2"
        )
        
    google_data = response.json()
    
    email = google_data.get("email")
    google_id = google_data.get("sub")  
    
    if not email or not google_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Token Google nie zawiera wymaganych informacji profilowych"
        )
        
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        user = User(
            email=email,
            oauth_provider="google",
            oauth_id=google_id,
            current_tariff="G11"  
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if not user.oauth_id:
            user.oauth_provider = "google"
            user.oauth_id = google_id
            db.commit()
            db.refresh(user)

    return {
        "status": "authenticated",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "current_tariff": user.current_tariff
        }
    }
    
class RegisterLocalRequest(BaseModel):
    email: str
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Hasło musi mieć co najmniej 8 znaków.")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Hasło musi zawierać co najmniej jedną wielką literę.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Hasło musi zawierać co najmniej jedną małą literę.")
        if not re.search(r"\d", v):
            raise ValueError("Hasło musi zawierać co najmniej jedną cyfrę.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Hasło musi zawierać co najmniej jeden znak specjalny (!@#$...).")
        return v

@router.post("/register")
async def register_local(payload: RegisterLocalRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Użytkownik o tym adresie e-mail już istnieje."
        )

    new_user = User(
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        current_tariff="G11"
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "status": "registered",
        "user": {
            "id": str(new_user.id),
            "email": new_user.email,
            "current_tariff": new_user.current_tariff
        }
    }
    
class LoginLocalRequest(BaseModel):
    email: str
    password: str

@router.post("/login")
async def login_local(payload: LoginLocalRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy adres e-mail lub hasło."
        )

    return {
        "status": "authenticated",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "current_tariff": user.current_tariff
        }
    }
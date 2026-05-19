from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import httpx
from pydantic import BaseModel, EmailStr
from app.database import get_db
from app.models.models import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

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
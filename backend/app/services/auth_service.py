import re
import jwt
from fastapi import HTTPException, status
from passlib.context import CryptContext
from google.oauth2 import id_token
from google.auth.transport import requests
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError

from app.repositories.user_repository import UserRepository
from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    CLIENT_ID,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
    SIGNATURE_ALGORITHM,
)



class AuthService:
    MAX_PASSWORD_BYTES = 72

    def __init__(self, repository: UserRepository):
        self.repository = repository
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


    @staticmethod
    def validate_password(password: str) -> None:
        if len(password.encode("utf-8")) > AuthService.MAX_PASSWORD_BYTES:
            raise ValueError("Hasło może mieć maksymalnie 72 bajty.")
        if len(password) < 8:
            raise ValueError("Hasło musi mieć co najmniej 8 znaków.")
        if not re.search(r"[A-Z]", password):
            raise ValueError("Hasło musi zawierać co najmniej jedną wielką literę.")
        if not re.search(r"[a-z]", password):
            raise ValueError("Hasło musi zawierać co najmniej jedną małą literę.")
        if not re.search(r"\d", password):
            raise ValueError("Hasło musi zawierać co najmniej jedną cyfrę.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValueError("Hasło musi zawierać co najmniej jeden znak specjalny (!@#$...).")
        

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)


    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)


    def normalize_email(self, email: str) -> str:
        return email.strip().lower()
    
    def register_local_user(self, email: str, password: str):
        email = self.normalize_email(email)
        existing_user = self.repository.get_by_email(email)

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Użytkownik o podanym adresie e-mail już istnieje.",
            )

        try:
            self.validate_password(password)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        try:
            user = self.repository.create(
                email=email,
                password_hash=self.get_password_hash(password),
                provider="local",
            )
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Użytkownik o podanym adresie e-mail już istnieje.",
            )

        return self.generate_auth_tokens(user.id)

    def login_local_user(self, email: str, password: str):
        email = self.normalize_email(email)
        user = self.repository.get_by_email(email)

        if not user or user.provider != "local" or not self.verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Nieprawidłowy adres e-mail, hasło lub sposób logowania.",
            )
        
        return self.generate_auth_tokens(user.id)
        

    def authenticate_google_user(self, google_id_token: str):
        try: 
            idinfo = id_token.verify_oauth2_token(google_id_token, requests.Request(), CLIENT_ID)
            self.validate_google_token(idinfo)

            email = self.normalize_email(idinfo["email"])
            user = self.repository.get_by_provider_id("google", idinfo["sub"])
            if user:
                return self.generate_auth_tokens(user.id)

            user = self.repository.get_by_email(email)
            if user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Użytkownik o podanym adresie e-mail już istnieje.",
                )
            
            try:
                user = self.repository.get_or_create_user(
                    provider_id=idinfo["sub"],
                    email=email,
                    provider="google",
                )
            except IntegrityError:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Użytkownik o podanym adresie e-mail już istnieje.",
                )

            return self.generate_auth_tokens(user.id)
        
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Nieprawidłowy lub wygasły token autoryzacyjny Google",
            )


    def generate_token(self, user_id, token_type: str, expire_time: datetime) -> str:
        payload = {
            "sub": str(user_id),
            "type": token_type,
            "exp": expire_time
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=SIGNATURE_ALGORITHM)


    def generate_auth_tokens(self, user_id: str) -> dict:
        time_now = datetime.now(timezone.utc)

        access_token = self.generate_token(user_id, "access", time_now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        refresh_token = self.generate_token(user_id, "refresh", time_now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))
        hashed_refresh_token = self.pwd_context.hash(refresh_token)
        self.repository.save_refresh_token(
            user_id,
            hashed_refresh_token,
            time_now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token
        }

    def validate_google_token(self, token: dict) -> None:
        if not token.get("sub") or not token.get("email") or not token.get("email_verified"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nieprawidłowy token Google.",
            )

    def validate_token(self, token: str, expected_type: str) -> dict:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[SIGNATURE_ALGORITHM])
            if payload.get("type") != expected_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Nieprawidłowy typ tokenu.",
                )

            if expected_type == "refresh":
                stored_token = self.repository.get_refresh_token(payload.get("sub"))
                expires_at = stored_token.expires_at if stored_token else None
                current_time = datetime.now(timezone.utc).replace(tzinfo=None)
                if (
                    not stored_token
                    or expires_at is None
                    or expires_at <= current_time
                    or not self.pwd_context.verify(token, stored_token.token_hash)
                ):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Nieprawidłowy token odświeżania.",
                    )
                
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token wygasł.",
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Nieprawidłowy token.",
            )


    def generate_access_token(self, refresh_token: str) -> str:
        token_payload = self.validate_token(refresh_token, "refresh")
        user_id = token_payload.get("sub")
        time_now = datetime.now(timezone.utc)
        return self.generate_token(user_id, "access", time_now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


    def invalidate_token(self, refresh_token: str) -> None:
        token_payload = self.validate_token(refresh_token, "refresh")
        user_id = token_payload.get("sub")
        deleted = self.repository.delete_refresh_token(user_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nieprawidłowy token odświeżania lub użytkownik nie istnieje.",
            )
        

    def refresh_tokens(self, refresh_token: str) -> dict:
        token_payload = self.validate_token(refresh_token, "refresh")
        user_id = token_payload.get("sub")
        new_tokens = self.generate_auth_tokens(user_id)
        return new_tokens

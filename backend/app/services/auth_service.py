import re
import httpx
from fastapi import HTTPException, status
from passlib.context import CryptContext
from app.repositories.user_repository import UserRepository



class AuthService:
    def __init__(self, repository: UserRepository | None = None):
        if repository is None:
            raise ValueError("UserRepository is required")
        self.repository = repository
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    async def fetch_google_user_data(self, id_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}")
        if response.status_code != status.HTTP_200_OK:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Niepoprawny lub wygasły token Google OAuth2",
            )

        google_data = response.json()
        if not google_data.get("email") or not google_data.get("sub"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token Google nie zawiera wymaganych informacji profilowych",
            )
        return google_data

    def authenticate_google_user(self, email: str, google_id: str):
        user = self.repository.get_by_email(email)

        if not user:
            return self.repository.create(
                email=email,
                oauth_provider="google",
                oauth_id=google_id,
                current_tariff="G11",
            )

        if not user.oauth_id:
            user.oauth_provider = "google"
            user.oauth_id = google_id
            self.repository.db.commit()
            self.repository.db.refresh(user)

        return user

    def register_local_user(self, email: str, password: str):
        existing_user = self.repository.get_by_email(email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Użytkownik o tym adresie e-mail już istnieje.",
            )

        return self.repository.create(
            email=email,
            password_hash=self.get_password_hash(password),
            current_tariff="G11",
        )

    def login_local_user(self, email: str, password: str):
        user = self.repository.get_by_email(email)
        if not user or not self.verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Nieprawidłowy adres e-mail lub hasło.",
            )
        return user

    @staticmethod
    def serialize_user(user) -> dict:
        return {
            "id": str(user.id),
            "email": user.email,
            "current_tariff": user.current_tariff,
        }

    @staticmethod
    def validate_password(password: str) -> None:
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

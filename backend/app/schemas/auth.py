from pydantic import BaseModel, EmailStr, field_validator

from app.services.auth_service import AuthService


class GoogleAuthRequest(BaseModel):
    id_token: str


class RegisterLocalRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        AuthService.validate_password(value)
        return value


class LoginLocalRequest(BaseModel):
    email: EmailStr
    password: str
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.services.auth_service import AuthService



class RegisterLocalRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        AuthService.validate_password(value)
        return value


class LoginLocalRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    google_code: str = Field(min_length=1)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
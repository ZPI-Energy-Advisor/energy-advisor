from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.other import TariffTypeEnum



class TariffOut(BaseModel):
    id: int
    code: str = Field(validation_alias="name")
    type: str
    description: str | None = None
    profile_tariff_type: TariffTypeEnum | None = None

    model_config = ConfigDict(from_attributes=True)


class TariffListResponse(BaseModel):
    status: str
    tariffs: list[TariffOut]


class TariffUpdateRequest(BaseModel):
    email: EmailStr
    new_tariff: str

from pydantic import BaseModel, ConfigDict, EmailStr



class TariffOut(BaseModel):
    id: int
    name: str
    type: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TariffListResponse(BaseModel):
    status: str
    tariffs: list[TariffOut]


class TariffUpdateRequest(BaseModel):
    email: EmailStr
    new_tariff: str
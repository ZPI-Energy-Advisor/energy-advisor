from pydantic import BaseModel, ConfigDict, Field

from app.schemas.other import TariffTypeEnum



class TariffOut(BaseModel):
    id: int
    code: str = Field(validation_alias="name")
    type: str
    description: str | None = None
    profile_tariff_type: TariffTypeEnum | None = None

    model_config = ConfigDict(from_attributes=True)


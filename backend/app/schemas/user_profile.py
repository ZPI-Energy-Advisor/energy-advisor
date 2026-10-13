from uuid import UUID
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field



class PropertyTypeEnum(str, Enum):
    APARTMENT = "apartment"
    SINGLE_FAMILY_HOUSE = "single_family_house"
    TERRACE_HOUSE = "terrace_house"
    RECREATIONAL_COTTAGE = "recreational_cottage"
    OTHER = "other"    


class UserProfile(BaseModel):
    type_of_property: PropertyTypeEnum
    heating_area_m2: float = Field(gt=0, le=10000)
    place_latitude: float | None = Field(default=None, ge=-90, le=90)
    place_longitude: float | None = Field(default=None, ge=-180, le=180)
    number_of_residents: int = Field(gt=0)
    current_tariff_id: int | None = Field(default=None, gt=0)

    model_config = ConfigDict(from_attributes=True)
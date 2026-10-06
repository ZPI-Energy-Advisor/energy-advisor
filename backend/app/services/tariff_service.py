
from app.repositories.tariff_repository import TariffRepository
from app.schemas.tariff import TariffListResponse, TariffOut



class TariffService:
    def __init__(self, repository: TariffRepository):
        self.repository = repository

    def get_all(self) -> TariffListResponse:
        tariffs = self.repository.get_all()
        return TariffListResponse(
            status="success",
            tariffs=[TariffOut.model_validate(tariff) for tariff in tariffs],
        )
    
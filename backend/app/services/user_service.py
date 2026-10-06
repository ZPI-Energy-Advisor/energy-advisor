from fastapi import HTTPException

from app.repositories.tariff_repository import TariffRepository
from app.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, repository: UserRepository, tariff_repository: TariffRepository):
        self.repository = repository
        self.tariff_repository = tariff_repository

    def update_current_tariff(self, email: str, tariff: str) -> dict:
        user = self.repository.get_by_email(email)
        if not user:
            raise HTTPException(status_code=404, detail="Nie znaleziono użytkownika.")

        if not self.tariff_repository.get_by_name(tariff):
            raise HTTPException(status_code=404, detail=f"Nie znaleziono taryfy {tariff}.")

        user.current_tariff = tariff
        self.repository.save(user)

        return {
            "status": "success",
            "new_tariff": user.current_tariff,
        }

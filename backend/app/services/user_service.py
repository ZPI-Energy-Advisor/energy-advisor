from fastapi import HTTPException

from app.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def update_current_tariff(self, email: str, tariff: str) -> dict:
        user = self.repository.get_by_email(email)
        if not user:
            raise HTTPException(status_code=404, detail="Nie znaleziono użytkownika.")

        user.current_tariff = tariff
        self.repository.db.commit()
        self.repository.db.refresh(user)

        return {
            "status": "success",
            "new_tariff": user.current_tariff,
        }

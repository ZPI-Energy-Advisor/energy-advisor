from uuid import UUID
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.Token import Token
from app.models.User import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> User:
        user = User(**kwargs)
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise
        self.db.refresh(user)
        return user

    def get_by_id(self, user_id: UUID) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()
    
    def get_by_email(self, email: str):
        return self.db.query(User).filter(User.email == email).first()

    def get_by_provider_id(self, provider: str, provider_id: str):
        return self.db.query(User).filter_by(
            provider=provider,
            provider_id=provider_id,
        ).first()

    def get_or_create_user(self, provider_id: str, email: str, provider: str) -> User:
        user = self.db.query(User).filter_by(provider_id=provider_id, provider=provider).first()
        if not user:
            user = User(provider_id=provider_id, email=email, provider=provider)
            self.db.add(user)
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                raise
            self.db.refresh(user)
        return user

    def get_refresh_token(self, user_id: str):
        return self.db.query(Token).filter_by(user_id=user_id).first()

    def save_refresh_token(self, user_id: str, token_hash: str, expires_at: datetime):
        token = self.get_refresh_token(user_id)
        if not token:
            token = Token(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
            self.db.add(token)
        else:
            token.token_hash = token_hash
            token.expires_at = expires_at
        self.db.commit()
        self.db.refresh(token)
        return token

    def delete_refresh_token(self, user_id: str) -> bool:
        token = self.get_refresh_token(user_id)
        if not token:
            return False
        self.db.delete(token)
        self.db.commit()
        return True
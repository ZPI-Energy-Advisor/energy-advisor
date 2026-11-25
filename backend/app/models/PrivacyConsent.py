import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class PrivacyConsent(Base):
    """Akceptacja polityki prywatności: która wersja, kiedy i gdzie (rejestracja, Google, ponowna akceptacja).
    Wiersze tylko przybywają, więc historia akceptacji zostaje do usunięcia konta."""

    __tablename__ = "privacy_consents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_version = Column(String(32), nullable=False)
    accepted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source = Column(String(20), nullable=False)

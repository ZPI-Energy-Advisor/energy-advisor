import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class DayPlan(Base):
    """Plan pracy urządzeń na dzień (ZP-112): wynik rdzenia harmonogramowania dla ustawień użytkownika.

    Jeden plan na użytkownika i dzień: ponowne ułożenie nadpisuje plan i wraca do szkicu (`draft`),
    a zatwierdzenie (`approved`) oznacza, że użytkownik go przyjął. `result` to treść planu w kształcie
    `DayPlanOut` (schemas/day_plan.py) bez pól nagłówka: przydziały, koszty, ceny i uwagi.
    """

    __tablename__ = "day_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "plan_date", name="uq_day_plan_user_date"),
        CheckConstraint("status IN ('draft', 'approved')", name="ck_day_plan_status"),
    )

    DRAFT = "draft"
    APPROVED = "approved"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Indeks na user_id zapewnia ograniczenie unikalności (user_id, plan_date).
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default=DRAFT)
    result = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)

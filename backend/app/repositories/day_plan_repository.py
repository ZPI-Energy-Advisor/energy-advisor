from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.DayPlan import DayPlan


class DayPlanRepository:
    """Plany pracy urządzeń na dzień (ZP-112): jeden na użytkownika i dzień."""

    def __init__(self, db: Session):
        self.db = db

    def save(self, user_id: UUID, plan_date: date, result: dict) -> DayPlan:
        """Zapisuje plan dnia; ponowne ułożenie nadpisuje poprzedni plan tego dnia i wraca do szkicu."""
        plan = self.db.execute(
            select(DayPlan).where(DayPlan.user_id == user_id, DayPlan.plan_date == plan_date)
        ).scalar_one_or_none()
        if plan is None:
            plan = DayPlan(user_id=user_id, plan_date=plan_date)
            self.db.add(plan)
        plan.result = result
        plan.status = DayPlan.DRAFT
        plan.approved_at = None
        plan.created_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def latest(self, user_id: UUID) -> DayPlan | None:
        return self.db.execute(
            select(DayPlan).where(DayPlan.user_id == user_id).order_by(DayPlan.created_at.desc()).limit(1)
        ).scalar_one_or_none()

    def get(self, user_id: UUID, plan_id: UUID) -> DayPlan | None:
        return self.db.execute(
            select(DayPlan).where(DayPlan.id == plan_id, DayPlan.user_id == user_id)
        ).scalar_one_or_none()

    def approve(self, plan: DayPlan) -> DayPlan:
        plan.status = DayPlan.APPROVED
        plan.approved_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(plan)
        return plan

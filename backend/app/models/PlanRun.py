import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class PlanRun(Base):
    """Przebieg planu dnia w symulacji Smart Home.

    Zatwierdzony plan trafia do huba jako komendy ze `start_at` na dobę planu. Urządzenia stałe (światło,
    lodówka, czajnik…) startują wyłączone i włącza je użytkownik. Z historii dnia referencyjnego (`history_day`)
    pracują tylko produkcja PV oraz pompa ciepła i bojler odznaczone w planie, bo plan zakłada, że chodzą same.
    Zużycie i awarie
    przebiegu to zdarzenia huba z tym samym `simulation_id` (tabela home_events), więc tu trzymamy tylko to,
    czego zdarzenia nie mają.

    `items` to migawka pozycji planu z wynikiem komendy huba: ponowne ułożenie planu nadpisuje wiersz
    day_plans, a przebieg ma dalej opisywać to, co faktycznie wysłaliśmy. `replay` opisuje odtworzenie historii
    w kształcie PlanRunReplay.

    Status: `running` od uruchomienia, `completed` gdy zegar przebiegu minie koniec planu, `ended` po
    „Zakończ”, `superseded` gdy hub zaczął inną symulację (nowy przebieg, ustawienie doby, restart huba).
    """

    __tablename__ = "plan_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'ended', 'superseded')", name="ck_plan_run_status"),
        Index("ix_plan_runs_user_started", "user_id", "started_at"),
    )

    RUNNING = "running"
    COMPLETED = "completed"
    ENDED = "ended"
    SUPERSEDED = "superseded"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    day_plan_id = Column(
        UUID(as_uuid=True), ForeignKey("day_plans.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    plan_date = Column(Date, nullable=False)
    simulation_id = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default=RUNNING)
    horizon_start = Column(DateTime(timezone=True), nullable=False)
    horizon_end = Column(DateTime(timezone=True), nullable=False)
    # Najnowszy z dni referencyjnych odtwarzanych urządzeń; NULL, gdy nie ma czego odtwarzać.
    history_day = Column(Date, nullable=True)
    items = Column(JSONB, nullable=False)
    replay = Column(JSONB, nullable=False)
    # Urządzenia odtwarzane z historii, które hub przyjął: [{"device_id", "history_day", "history_kwh"}],
    # energia ujemna dla PV. Dzień referencyjny liczymy dla każdego urządzenia osobno, jak plan.
    replayed_devices = Column(JSONB, nullable=False, default=list)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    # Czas symulacji, na którym przebieg się skończył (koniec planu albo chwila „Zakończ”).
    ended_sim_time = Column(DateTime(timezone=True), nullable=True)

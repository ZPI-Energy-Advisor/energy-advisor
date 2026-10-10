from uuid import UUID

from sqlalchemy.orm import Session

from app.models.Simulation import Simulation



class SimulationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: UUID, results):
        simulation = Simulation(user_id=user_id, results=results)
        self.db.add(simulation)
        self.db.commit()
        self.db.refresh(simulation)
        return simulation

    def get_latest_by_user_id(self, user_id):
        return (
            self.db.query(Simulation)
            .filter(Simulation.user_id == user_id)
            .order_by(Simulation.created_at.desc(), Simulation.id.desc())
            .first()
        )

    def get_by_id(self, simulation_id: UUID):
        return self.db.query(Simulation).filter(Simulation.id == simulation_id).first()

    def get_by_id_for_user(self, simulation_id: UUID, user_id: UUID):
        return (
            self.db.query(Simulation)
            .filter(
                Simulation.id == simulation_id,
                Simulation.user_id == user_id,
            )
            .first()
        )

from sqlalchemy.orm import Session

from app.models.Simulation import Simulation



class SimulationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id, results):
        simulation = Simulation(user_id=user_id, results=results)
        self.db.add(simulation)
        self.db.commit()
        self.db.refresh(simulation)
        return simulation

    def get_latest_by_user_id(self, user_id):
        return (
            self.db.query(Simulation)
            .filter(Simulation.user_id == user_id)
            .order_by(Simulation.created_at.desc())
            .first()
        )

    def get_by_id(self, simulation_id):
        return self.db.query(Simulation).filter(Simulation.id == simulation_id).first()

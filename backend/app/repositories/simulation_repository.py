from uuid import UUID
from sqlalchemy.orm import Session
from app.models.UserProfile import UserProfile as UserProfileModel
from app.models.EnergyDataFile import EnergyDataFile  # noqa: F401 - rejestruje tabelę dla FK
from app.models.Simulation import Simulation
from app.schemas.user_profile import UserProfile


class SimulationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: UUID, energy_data_file_id: UUID, results):
        simulation = Simulation(user_id=user_id, energy_data_file_id=energy_data_file_id, results=results)
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

    def get_latest_by_file_id(self, energy_data_file_id: UUID):
        return (
            self.db.query(Simulation)
            .filter(Simulation.energy_data_file_id == energy_data_file_id)
            .order_by(Simulation.created_at.desc(), Simulation.id.desc())
            .first()
        )

    def get_latest_by_file_ids(self, energy_data_file_ids: list[UUID]) -> dict[UUID, Simulation]:
        """Najnowsza symulacja każdego z podanych plików, w postaci {id pliku: symulacja}."""
        if not energy_data_file_ids:
            return {}
        simulations = (
            self.db.query(Simulation)
            .filter(Simulation.energy_data_file_id.in_(energy_data_file_ids))
            .order_by(Simulation.created_at.desc(), Simulation.id.desc())
            .all()
        )
        latest = {}
        for simulation in simulations:
            latest.setdefault(simulation.energy_data_file_id, simulation)
        return latest

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


    def create_user_profile(self, user_id: UUID, profile_data: UserProfile):
        profile = UserProfileModel(user_id=user_id, **profile_data.model_dump())
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def get_user_profile(self, user_id: UUID):
        return (
            self.db.query(UserProfileModel)
            .filter(UserProfileModel.user_id == user_id)
            .first()
        )


    def update_user_profile(self, user_id: UUID, new_profile_data: UserProfile):
        profile = self.get_user_profile(user_id)

        if profile is None:
            return None

        for field, value in new_profile_data.model_dump().items():
            setattr(profile, field, value)

        self.db.commit()
        self.db.refresh(profile)
        return profile

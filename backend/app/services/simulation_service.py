from app.repositories.simulation_repository import SimulationRepository
from app.schemas.simulation import SimulationResultResponse
from uuid import UUID


class SimulationService:
    def __init__(self, repository: SimulationRepository):
        self.repository = repository

    def get_latest_by_user_id(self, user_id: UUID):
        simulation = self.repository.get_latest_by_user_id(user_id)
        if not simulation:
            return {"status": "no_data", "results": None}

        return SimulationResultResponse(
            status="success",
            simulation_id=str(simulation.id),
            created_at=simulation.created_at,
            results=simulation.results,
        )

    def get_simulation_results(self, simulation_id: UUID, user_id: UUID):
        simulation = self.repository.get_by_id_for_user(simulation_id, user_id)
        if not simulation:
            return None

        return SimulationResultResponse(
            status="success",
            simulation_id=str(simulation.id),
            created_at=simulation.created_at,
            results=simulation.results,
        )

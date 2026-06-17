from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Simulation

router = APIRouter(
    prefix="/results",
    tags=["Results"]
)

@router.get("/user/{user_id}")
async def get_latest_user_simulation(user_id: str, db: Session = Depends(get_db)):# Szukamy w bazie symulacji, gdzie user_id się zgadza, sortujemy od najnowszej
    simulation = db.query(Simulation)\
        .filter(Simulation.user_id == user_id)\
        .order_by(Simulation.created_at.desc())\
        .first()
    
    if not simulation:
        return {
            "status": "no_data",
            "results": None
        }
        
    return {
        "status": "success",
        "simulation_id": str(simulation.id),
        "created_at": simulation.created_at,
        "results": simulation.results
    }

@router.get("/{simulation_id}")
async def get_simulation_results(simulation_id: str, db: Session = Depends(get_db)):
    simulation = db.query(Simulation).filter(Simulation.id == simulation_id).first()
    if not simulation:
        raise HTTPException(status_code=404, detail="Nie znaleziono wyników dla podanego ID.")
    return {
        "status": "success",
        "simulation_id": str(simulation.id),
        "created_at": simulation.created_at,
        "results": simulation.results
    }
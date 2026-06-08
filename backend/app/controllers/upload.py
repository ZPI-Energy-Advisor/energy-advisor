from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Simulation, User
from app.services.calculations import calculate_all_tariffs

router = APIRouter(
    prefix="/upload",
    tags=["Upload & Simulation"]
)

@router.post("")
async def upload_energy_data(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Wymagany plik .csv")

    simulation_results = calculate_all_tariffs(file.file, db)

    dummy_user = db.query(User).first()
    if not dummy_user:
        dummy_user = User(email="test@advisor.pl")
        db.add(dummy_user)
        db.commit()
        db.refresh(dummy_user)

    new_simulation = Simulation(
        user_id=dummy_user.id,
        results=simulation_results
    )
    
    db.add(new_simulation)
    db.commit()
    db.refresh(new_simulation)

    return {
        "status": "success",
        "simulation_id": str(new_simulation.id),
        "file_name": file.filename,
        "summary": simulation_results,
        "message": "Symulacja dla wszystkich taryf zakończona i zapisana w bazie!"
    }


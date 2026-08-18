from app.database import get_db
from app.models.models import Simulation, User
from app.services.calculations import calculate_all_tariffs
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

router = APIRouter(prefix="/upload", tags=["Upload & Simulation"])


@router.post("")
async def upload_energy_data(
    file: UploadFile = File(...),
    user_email: str = Form(...),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Wymagany plik .csv")

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(
            status_code=404, detail="Nie znaleziono zalogowanego użytkownika."
        )

    simulation_results = calculate_all_tariffs(file.file, db)

    new_simulation = Simulation(user_id=user.id, results=simulation_results)

    db.add(new_simulation)
    db.commit()
    db.refresh(new_simulation)

    return {
        "status": "success",
        "simulation_id": str(new_simulation.id),
        "file_name": file.filename,
        "summary": simulation_results,
        "message": "Symulacja zakończona i zapisana na Twoim koncie!",
    }

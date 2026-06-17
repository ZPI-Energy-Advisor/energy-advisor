from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Tariff

router = APIRouter(
    prefix="/tariffs",
    tags=["Tariffs"]
)

@router.get("")
async def get_all_tariffs(db: Session = Depends(get_db)):
    # Pobieramy wszystkie taryfy z bazy danych
    tariffs = db.query(Tariff).all()
    
    # Wyciągamy same nazwy (np. "G11", "G12") do prostej listy dla Reacta
    tariff_names = [t.name for t in tariffs]
    
    return {
        "status": "success",
        "tariffs": tariff_names
    }
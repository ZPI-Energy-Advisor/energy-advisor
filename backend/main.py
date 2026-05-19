from fastapi import FastAPI
from app.controllers.auth import router as auth_router

app = FastAPI(title="Energy Advisor API")

app.include_router(auth_router)

@app.get("/")
def read_root():
    return {"message": "Energy Advisor API działa poprawnie"}
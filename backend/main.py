from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.controllers.auth import router as auth_router
from app.controllers.upload import router as upload_router
from app.controllers.results import router as results_router
app = FastAPI(title="Energy Advisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(results_router)

@app.get("/")
def read_root():
    return {"message": "Energy Advisor API działa poprawnie"}
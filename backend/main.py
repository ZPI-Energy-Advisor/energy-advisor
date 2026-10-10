import os
import jwt
from fastapi import APIRouter, FastAPI, Depends, HTTPException, status
from uuid import UUID
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer

from app.api.v1.auth import router as auth_router
from app.api.v1.upload import router as upload_router
from app.api.v1.results import router as results_router



app = FastAPI(title="Energy Advisor API")

api_router = APIRouter(prefix="/api")
v1_router = APIRouter(prefix="/v1")

v1_router.include_router(auth_router)
v1_router.include_router(upload_router)
v1_router.include_router(results_router)
# v1_router.include_router(tariffs_router)
api_router.include_router(v1_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

@api_router.get("/health", tags=["Health Check"])
def get_api_health():
    return {"message": "Energy Advisor API works fine!"}

app.include_router(api_router)
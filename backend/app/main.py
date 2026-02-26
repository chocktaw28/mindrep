"""
MindRep API
===========
FastAPI application entry point. Mount routers here.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import exercise, insights, mood, prescriptions, wearable

settings = get_settings()

app = FastAPI(
    title="MindRep API",
    description="Exercise as Precision Mental Health — API Backend",
    version="0.1.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url="/api/redoc" if settings.environment != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mood.router)
app.include_router(exercise.router)
app.include_router(wearable.router)
app.include_router(prescriptions.router)
app.include_router(insights.router)


@app.get("/api/v1/health")
async def health_check() -> dict:
    return {"status": "ok", "service": "mindrep-api"}

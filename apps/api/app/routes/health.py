from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db

router = APIRouter(tags=["system"])

@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "flowpay-api", "environment": settings.environment}

@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(select(1))
        return {"status": "ready", "database": "ok"}
    except Exception:
        raise HTTPException(503, "database_unavailable")

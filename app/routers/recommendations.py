"""Proactive recommendation endpoint — surfaces fresh skills based on history."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.recommender import get_recommendations

router = APIRouter(prefix="/api", tags=["recommendations"])


@router.get("/recommendations")
async def recommendations(db: AsyncSession = Depends(get_db)):
    """Return up to 10 fresh recommendations as a bare array (empty if no history)."""
    return await get_recommendations(db, limit=10)

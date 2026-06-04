from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.skill import Skill, UserInterest
from app.services.index import search
from app.services.recommender import get_recommendations

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
async def search_skills(
    q: str = Query(..., description="ลักษณะของ skill ที่อยากได้ (ภาษาอะไรก็ได้)"),
    top_k: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search — คืนรายการ skill ที่ตรงกับ query."""
    hits = search(q, top_k=top_k)
    if not hits:
        return {"query": q, "results": [], "recommendations": []}

    skill_ids = [sid for sid, _ in hits]
    score_map = {sid: score for sid, score in hits}

    result = await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))
    skills = {s.id: s for s in result.scalars().all()}

    # Save interest history
    top_ids_str = ",".join(str(sid) for sid in skill_ids[:10])
    db.add(UserInterest(query=q, top_skill_ids=top_ids_str))
    await db.commit()

    results = [
        {
            "id": sid,
            "name": skills[sid].name,
            "description": skills[sid].description,
            "source": skills[sid].source,
            "source_url": skills[sid].source_url,
            "tags": skills[sid].tags.split(",") if skills[sid].tags else [],
            "score": score_map[sid],
        }
        for sid in skill_ids
        if sid in skills
    ]

    recommendations = await get_recommendations(db, limit=5)

    return {"query": q, "results": results, "recommendations": recommendations}


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if skill is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill

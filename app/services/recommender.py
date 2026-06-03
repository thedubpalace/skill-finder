"""
Proactive recommendation service.
Reads user interest history from DB and surfaces skills that are
semantically similar to past queries but were NOT already returned.
"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.skill import UserInterest, Skill
from app.services.index import search


async def get_recommendations(db: AsyncSession, limit: int = 5) -> list[dict]:
    """Return skills similar to past interests that the user hasn't seen recently."""
    result = await db.execute(
        select(UserInterest).order_by(UserInterest.created_at.desc()).limit(20)
    )
    interests = result.scalars().all()
    if not interests:
        return []

    seen_ids: set[int] = set()
    for interest in interests:
        for sid in interest.top_skill_ids.split(","):
            if sid.strip().isdigit():
                seen_ids.add(int(sid.strip()))

    # Aggregate queries into a single representative text
    combined_query = " ".join(i.query for i in interests[:5])
    candidates = search(combined_query, top_k=20)

    # Filter out already-seen skills
    fresh = [(sid, score) for sid, score in candidates if sid not in seen_ids][:limit]

    if not fresh:
        return []

    fresh_ids = [sid for sid, _ in fresh]
    result = await db.execute(select(Skill).where(Skill.id.in_(fresh_ids)))
    skills = {s.id: s for s in result.scalars().all()}

    return [
        {
            "id": sid,
            "name": skills[sid].name,
            "description": skills[sid].description,
            "source_url": skills[sid].source_url,
            "score": score,
        }
        for sid, score in fresh
        if sid in skills
    ]

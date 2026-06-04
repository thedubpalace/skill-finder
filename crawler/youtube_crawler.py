"""
YouTube crawler — searches the YouTube Data API v3 for AI tooling tutorials/reviews.

Requires YOUTUBE_API_KEY env var. If absent, logs a warning and returns [] (no crash).
API: https://www.googleapis.com/youtube/v3/search
Rate limit: tenacity retry + exponential back-off.
"""
from __future__ import annotations
import os
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.skill import Skill

YOUTUBE_API = "https://www.googleapis.com/youtube/v3/search"

KEYWORDS = [
    "MCP server tutorial",
    "Claude plugin",
    "AI tool review",
    "LLM tool",
    "AI agent build",
]


def _api_key() -> str:
    return getattr(settings, "youtube_api_key", "") or os.getenv("YOUTUBE_API_KEY", "")


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _search_keyword(client: httpx.AsyncClient, keyword: str, key: str, max_results: int = 20) -> list[dict]:
    resp = await client.get(
        YOUTUBE_API,
        params={
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "order": "relevance",
            "maxResults": max_results,
            "key": key,
        },
        headers={"User-Agent": "skill-finder/1.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


async def crawl_youtube(db: AsyncSession):
    """Fetch YouTube videos via Data API v3 and upsert into DB. No-op without API key."""
    key = _api_key()
    if not key:
        print("[youtube_crawler] YOUTUBE_API_KEY not set — skipping YouTube crawl")
        return

    async with httpx.AsyncClient() as client:
        for keyword in KEYWORDS:
            try:
                items = await _search_keyword(client, keyword, key)
            except Exception as e:
                print(f"[youtube_crawler] keyword={keyword!r} error: {e}")
                continue

            for item in items:
                video_id = (item.get("id") or {}).get("videoId")
                snippet = item.get("snippet") or {}
                if not video_id:
                    continue

                url = f"https://youtube.com/watch?v={video_id}"
                existing = await db.execute(
                    select(Skill).where(Skill.source_url == url)
                )
                if existing.scalar_one_or_none():
                    continue  # already indexed

                title = snippet.get("title") or ""
                description = (snippet.get("description") or "")[:300]
                channel = snippet.get("channelTitle") or "youtube"

                skill = Skill(
                    name=title,
                    description=description,
                    source="youtube",
                    source_url=url,
                    category=channel,
                    tags=f"youtube,{channel}",
                )
                db.add(skill)

            await db.commit()
    print("[youtube_crawler] done")

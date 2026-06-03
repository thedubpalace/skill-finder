"""
GitHub crawler — searches GitHub for repositories tagged with skill-related topics.
Uses GitHub Search API. Respects rate limits via tenacity retry + exponential back-off.

Auth: set GITHUB_TOKEN in .env to raise limit from 10 req/min (unauth) to 30 req/min.
"""
from __future__ import annotations
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.skill import Skill

SEARCH_TOPICS = [
    "claude-plugin", "mcp-server", "ai-skill", "llm-tool",
    "langchain-tool", "openai-plugin", "chatgpt-plugin",
]

GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "skill-finder/0.1"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _fetch_topic(client: httpx.AsyncClient, topic: str, per_page: int = 30) -> list[dict]:
    resp = await client.get(
        f"{GITHUB_API}/search/repositories",
        params={"q": f"topic:{topic}", "per_page": per_page, "sort": "stars"},
        headers=_headers(),
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


async def crawl_github(db: AsyncSession):
    """Fetch skills from GitHub and upsert into DB."""
    async with httpx.AsyncClient() as client:
        for topic in SEARCH_TOPICS:
            try:
                items = await _fetch_topic(client, topic)
            except Exception as e:
                print(f"[github_crawler] topic={topic} error: {e}")
                continue

            for item in items:
                existing = await db.execute(
                    select(Skill).where(Skill.source_url == item["html_url"])
                )
                if existing.scalar_one_or_none():
                    continue  # already indexed

                skill = Skill(
                    name=item["full_name"],
                    description=item.get("description") or "",
                    source="github",
                    source_url=item["html_url"],
                    category=topic,
                    tags=",".join(item.get("topics", [])),
                )
                db.add(skill)

            await db.commit()
    print("[github_crawler] done")

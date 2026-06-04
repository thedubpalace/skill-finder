"""
Hacker News crawler — searches Algolia HN Search API (free, no key) for "Show HN" posts
about AI tools, MCP servers, LLM tooling, Claude integrations, and agents.

API: http://hn.algolia.com/api/v1/search
Rate limit: tenacity retry + exponential back-off.
"""
from __future__ import annotations
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.skill import Skill

HN_API = "http://hn.algolia.com/api/v1/search"

KEYWORDS = [
    "Show HN AI tool",
    "Show HN MCP",
    "Show HN LLM tool",
    "Show HN Claude",
    "Show HN agent",
]


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _fetch_keyword(client: httpx.AsyncClient, keyword: str, hits: int = 30) -> list[dict]:
    resp = await client.get(
        HN_API,
        params={
            "query": keyword,
            "tags": "story",
            "hitsPerPage": hits,
            # Algolia ranks by relevance + points by default for /search
        },
        headers={"User-Agent": "skill-finder/1.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json().get("hits", [])


async def crawl_hn(db: AsyncSession):
    """Fetch Show HN posts from Algolia HN Search and upsert into DB."""
    # http://hn.algolia.com 301-redirects to https — follow it transparently.
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for keyword in KEYWORDS:
            try:
                hits = await _fetch_keyword(client, keyword)
            except Exception as e:
                print(f"[hn_crawler] keyword={keyword!r} error: {e}")
                continue

            # Sort by points (popularity) descending — Algolia /search is relevance-ordered.
            hits.sort(key=lambda h: h.get("points") or 0, reverse=True)

            for hit in hits:
                object_id = hit.get("objectID")
                url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
                title = hit.get("title") or hit.get("story_title") or ""
                if not title:
                    continue

                existing = await db.execute(
                    select(Skill).where(Skill.source_url == url)
                )
                if existing.scalar_one_or_none():
                    continue  # already indexed

                story_text = (hit.get("story_text") or "").strip()
                description = story_text[:300] if story_text else title

                skill = Skill(
                    name=title,
                    description=description,
                    source="hn",
                    source_url=url,
                    category="show-hn",
                    tags="hackernews,show-hn",
                )
                db.add(skill)

            await db.commit()
    print("[hn_crawler] done")

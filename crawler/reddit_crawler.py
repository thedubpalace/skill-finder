"""
Reddit crawler — reads public hot posts via the Reddit JSON API (free, no key, read-only)
from AI-related subreddits and keeps posts whose titles mention tools/plugins/agents.

API: https://www.reddit.com/r/<subreddit>/hot.json?limit=25
Rate limit: anonymous ~1 req/2s — sleeps 2s between subreddits, tenacity retry.
A descriptive User-Agent is required by Reddit.
"""
from __future__ import annotations
import asyncio
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.skill import Skill

SUBREDDITS = ["ClaudeAI", "MachineLearning", "LangChain", "artificial", "AIAssistants"]

KEYWORDS = ["tool", "plugin", "extension", "library", "framework", "mcp", "agent"]


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _fetch_subreddit(client: httpx.AsyncClient, subreddit: str, limit: int = 25) -> list[dict]:
    resp = await client.get(
        f"https://www.reddit.com/r/{subreddit}/hot.json",
        params={"limit": limit},
        headers={"User-Agent": "skill-finder/1.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    children = resp.json().get("data", {}).get("children", [])
    return [c.get("data", {}) for c in children]


def _matches_keyword(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in KEYWORDS)


async def crawl_reddit(db: AsyncSession):
    """Fetch hot posts from AI subreddits and upsert matching ones into DB."""
    async with httpx.AsyncClient() as client:
        for i, subreddit in enumerate(SUBREDDITS):
            if i > 0:
                await asyncio.sleep(2)  # respect Reddit anonymous rate limit

            try:
                posts = await _fetch_subreddit(client, subreddit)
            except Exception as e:
                print(f"[reddit_crawler] subreddit={subreddit!r} error: {e}")
                continue

            for post in posts:
                title = (post.get("title") or "").strip()
                if not title or not _matches_keyword(title):
                    continue

                permalink = post.get("permalink") or ""
                url = f"https://reddit.com{permalink}" if permalink else (post.get("url") or "")
                if not url:
                    continue

                existing = await db.execute(
                    select(Skill).where(Skill.source_url == url)
                )
                if existing.scalar_one_or_none():
                    continue  # already indexed

                selftext = (post.get("selftext") or "").strip()
                description = selftext[:300] if selftext else title

                skill = Skill(
                    name=title[:100],
                    description=description,
                    source="reddit",
                    source_url=url,
                    category=subreddit,
                    tags=f"reddit,{subreddit}",
                )
                db.add(skill)

            await db.commit()
    print("[reddit_crawler] done")

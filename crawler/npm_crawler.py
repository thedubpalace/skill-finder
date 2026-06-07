"""
npm crawler — searches the npm registry search API (free, no key) for AI/LLM/MCP packages.

API: https://registry.npmjs.org/-/v1/search?text=<keyword>&size=50
Rate limit: tenacity retry + exponential back-off.
"""
from __future__ import annotations
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.skill import Skill

NPM_API = "https://registry.npmjs.org/-/v1/search"

KEYWORDS = ["mcp", "llm-tool", "langchain", "claude-sdk", "openai-tool", "ai-agent"]


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _fetch_keyword(client: httpx.AsyncClient, keyword: str, size: int = 50) -> list[dict]:
    resp = await client.get(
        NPM_API,
        params={"text": keyword, "size": size},
        headers={"User-Agent": "skill-finder/1.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json().get("objects", [])


async def crawl_npm(db: AsyncSession):
    """Disabled — npm packages are not Claude Code skills."""
    print("[npm_crawler] skipped — not relevant for Claude Code skills")
    return


async def _crawl_npm_disabled(db: AsyncSession):
    async with httpx.AsyncClient() as client:
        for keyword in KEYWORDS:
            try:
                objects = await _fetch_keyword(client, keyword)
            except Exception as e:
                print(f"[npm_crawler] keyword={keyword!r} error: {e}")
                continue

            for obj in objects:
                package = obj.get("package", {})
                name = package.get("name")
                if not name:
                    continue

                url = f"https://www.npmjs.com/package/{name}"
                existing = await db.execute(
                    select(Skill).where(Skill.source_url == url)
                )
                if existing.scalar_one_or_none():
                    continue  # already indexed

                keywords = package.get("keywords") or []
                tags = ",".join(keywords[:10])

                skill = Skill(
                    name=name,
                    description=package.get("description") or "",
                    source="npm",
                    source_url=url,
                    category="npm-package",
                    tags=tags,
                )
                db.add(skill)

            await db.commit()
    print("[npm_crawler] done")

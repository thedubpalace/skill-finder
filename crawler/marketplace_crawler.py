"""
Marketplace crawler — placeholder for VS Code marketplace, npm, PyPI plugin discovery.
Implement each source by adding an async function and calling it from crawl_marketplace().
"""
from __future__ import annotations
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.skill import Skill
from sqlalchemy import select

VSCODE_API = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"


async def _crawl_vscode(db: AsyncSession):
    """Fetch AI/LLM-related VS Code extensions."""
    payload = {
        "filters": [{"criteria": [{"filterType": 8, "value": "Microsoft.VisualStudio.Code"},
                                   {"filterType": 10, "value": "ai agent"}],
                     "pageSize": 50, "pageNumber": 1}],
        "flags": 914,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                VSCODE_API,
                json=payload,
                headers={"Accept": "application/json;api-version=7.1-preview.1",
                         "Content-Type": "application/json"},
                timeout=15.0,
            )
            resp.raise_for_status()
            extensions = resp.json()["results"][0]["extensions"]
        except Exception as e:
            print(f"[marketplace_crawler] vscode error: {e}")
            return

        for ext in extensions:
            url = f"https://marketplace.visualstudio.com/items?itemName={ext['publisher']['publisherName']}.{ext['extensionName']}"
            existing = await db.execute(select(Skill).where(Skill.source_url == url))
            if existing.scalar_one_or_none():
                continue

            skill = Skill(
                name=ext["extensionName"],
                description=ext.get("shortDescription") or "",
                source="marketplace",
                source_url=url,
                category="vscode-extension",
                tags="vscode,extension",
            )
            db.add(skill)

        await db.commit()


async def crawl_marketplace(db: AsyncSession):
    print("[marketplace_crawler] skipped — not relevant for Claude Code skills")
    return

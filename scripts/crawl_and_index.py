"""
One-shot script: crawl all sources then rebuild FAISS index.
Run with: python scripts/crawl_and_index.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import init_db, AsyncSessionLocal
from app.services.index import build_index
from crawler.github_crawler import crawl_github
from crawler.marketplace_crawler import crawl_marketplace
from sqlalchemy import select
from app.models.skill import Skill


async def main():
    await init_db()
    async with AsyncSessionLocal() as db:
        print("Crawling GitHub...")
        await crawl_github(db)
        print("Crawling marketplaces...")
        await crawl_marketplace(db)
        print("Rebuilding FAISS index...")
        result = await db.execute(select(Skill))
        skills = result.scalars().all()
        ids = [s.id for s in skills]
        texts = [f"{s.name} {s.description} {s.tags}" for s in skills]
        build_index(ids, texts)
        print(f"Done — {len(ids)} skills indexed.")


if __name__ == "__main__":
    asyncio.run(main())

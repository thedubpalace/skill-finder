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
from crawler.hn_crawler import crawl_hn
from crawler.npm_crawler import crawl_npm
from crawler.pypi_crawler import crawl_pypi
from crawler.reddit_crawler import crawl_reddit
from crawler.youtube_crawler import crawl_youtube
from sqlalchemy import select
from app.models.skill import Skill


async def _run(label: str, coro_fn, db):
    """Run a crawler, logging and swallowing errors so one source can't abort the run."""
    print(f"Crawling {label}...")
    try:
        await coro_fn(db)
    except Exception as e:
        print(f"[crawl_and_index] {label} failed: {e}")


async def main():
    await init_db()
    async with AsyncSessionLocal() as db:
        await _run("GitHub", crawl_github, db)
        await _run("marketplaces", crawl_marketplace, db)
        await _run("Hacker News", crawl_hn, db)
        await _run("npm", crawl_npm, db)
        await _run("PyPI", crawl_pypi, db)
        await _run("Reddit", crawl_reddit, db)
        await _run("YouTube", crawl_youtube, db)
        print("Rebuilding FAISS index...")
        result = await db.execute(select(Skill))
        skills = result.scalars().all()
        ids = [s.id for s in skills]
        texts = [f"{s.name} {s.description} {s.tags}" for s in skills]
        build_index(ids, texts)
        print(f"Done — {len(ids)} skills indexed.")


if __name__ == "__main__":
    asyncio.run(main())

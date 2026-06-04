"""Admin endpoints — trigger crawl, rebuild index."""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/crawl")
async def trigger_crawl(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Start a background crawl of all configured sources."""
    from crawler.github_crawler import crawl_github
    from crawler.marketplace_crawler import crawl_marketplace
    from crawler.hn_crawler import crawl_hn
    from crawler.npm_crawler import crawl_npm
    from crawler.pypi_crawler import crawl_pypi
    from crawler.reddit_crawler import crawl_reddit
    from crawler.youtube_crawler import crawl_youtube
    background_tasks.add_task(crawl_github, db)
    background_tasks.add_task(crawl_marketplace, db)
    background_tasks.add_task(crawl_hn, db)
    background_tasks.add_task(crawl_npm, db)
    background_tasks.add_task(crawl_pypi, db)
    background_tasks.add_task(crawl_reddit, db)
    background_tasks.add_task(crawl_youtube, db)
    return {"status": "crawl started"}


@router.post("/rebuild-index")
async def rebuild_index(db: AsyncSession = Depends(get_db)):
    """Rebuild FAISS index from current DB contents."""
    from sqlalchemy import select
    from app.models.skill import Skill
    from app.services.index import build_index

    result = await db.execute(select(Skill))
    skills = result.scalars().all()
    ids = [s.id for s in skills]
    texts = [f"{s.name} {s.description} {s.tags}" for s in skills]
    build_index(ids, texts)
    return {"status": "index rebuilt", "skill_count": len(ids)}

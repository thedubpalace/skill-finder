"""
PyPI crawler — scrapes the PyPI search results page (free, no key) for AI/LLM/MCP packages,
then fetches each package's JSON metadata for summary + classifiers.

Search:  https://pypi.org/search/?q=<keyword>&o=-created  (HTML, parsed via BeautifulSoup)
Detail:  https://pypi.org/pypi/<package>/json
Rate limit: tenacity retry + exponential back-off.
"""
from __future__ import annotations
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.skill import Skill

PYPI_SEARCH = "https://pypi.org/search/"
PYPI_JSON = "https://pypi.org/pypi/{name}/json"

KEYWORDS = ["mcp", "langchain", "llm", "claude", "openai-tool", "ai-agent"]


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _search_keyword(client: httpx.AsyncClient, keyword: str, limit: int = 30) -> list[dict]:
    """Scrape the PyPI search page and return up to `limit` package summaries."""
    resp = await client.get(
        PYPI_SEARCH,
        params={"q": keyword, "o": "-created"},
        headers={"User-Agent": "skill-finder/1.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    results: list[dict] = []
    for snippet in soup.select("a.package-snippet")[:limit]:
        name_el = snippet.select_one("span.package-snippet__name")
        desc_el = snippet.select_one("p.package-snippet__description")
        if not name_el:
            continue
        results.append({
            "name": name_el.get_text(strip=True),
            "summary": desc_el.get_text(strip=True) if desc_el else "",
        })
    return results


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _fetch_classifiers(client: httpx.AsyncClient, name: str) -> str:
    """Fetch package JSON and build a short comma-separated tag string from classifiers."""
    resp = await client.get(
        PYPI_JSON.format(name=name),
        headers={"User-Agent": "skill-finder/1.0"},
        timeout=15.0,
    )
    resp.raise_for_status()
    info = resp.json().get("info", {})
    classifiers = info.get("classifiers") or []
    # Keep only the leaf of each classifier path, short and de-duplicated.
    leaves: list[str] = []
    for c in classifiers:
        leaf = c.split("::")[-1].strip()
        if leaf and leaf not in leaves:
            leaves.append(leaf)
    return ",".join(leaves[:8])


async def crawl_pypi(db: AsyncSession):
    """Disabled — PyPI packages are not Claude Code skills."""
    print("[pypi_crawler] skipped — not relevant for Claude Code skills")
    return


async def _crawl_pypi_disabled(db: AsyncSession):
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for keyword in KEYWORDS:
            try:
                packages = await _search_keyword(client, keyword)
            except Exception as e:
                print(f"[pypi_crawler] keyword={keyword!r} error: {e}")
                continue

            for pkg in packages:
                name = pkg["name"]
                url = f"https://pypi.org/project/{name}"
                existing = await db.execute(
                    select(Skill).where(Skill.source_url == url)
                )
                if existing.scalar_one_or_none():
                    continue  # already indexed

                try:
                    tags = await _fetch_classifiers(client, name)
                except Exception as e:
                    print(f"[pypi_crawler] classifiers name={name!r} error: {e}")
                    tags = "pypi"

                skill = Skill(
                    name=name,
                    description=pkg.get("summary") or "",
                    source="pypi",
                    source_url=url,
                    category="python-package",
                    tags=tags or "pypi",
                )
                db.add(skill)

            await db.commit()
    print("[pypi_crawler] done")

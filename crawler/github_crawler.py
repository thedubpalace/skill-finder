"""
GitHub crawler — discovers **Claude Code agent skills** on GitHub.

A Claude Code skill is a Markdown file living under `.claude/skills/` or
`.claude/agents/` in a repo, usually carrying a YAML frontmatter block:

    ---
    name: skill-name
    description: what this skill does
    ---
    content...

Strategy:
  1. GitHub Code Search API for the actual skill files
     (`path:.claude/skills extension:md`, `path:.claude/agents extension:md`).
  2. GitHub Repository Search API for repos topic-tagged as Claude Code skills.
For each file found we fetch its raw content, parse the frontmatter (regex-based,
no extra dependency) and store name/description.

Auth: set GITHUB_TOKEN in .env to raise the Code Search limit from
10 req/min (unauth) to 30 req/min. We sleep 2s between requests regardless.
"""
from __future__ import annotations
import asyncio
import re
from datetime import datetime, timezone
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models.skill import Skill

GITHUB_API = "https://api.github.com"

# Code Search queries — find the actual skill/agent Markdown files.
# Claude-Code-native skill files (platform: claude-code only).
CODE_QUERIES = [
    "path:.claude/skills extension:md",
    "path:.claude/agents extension:md",
]

# Cross-platform SKILL.md files (UiPath-style) — run on any agent.
CROSS_PLATFORM_QUERIES = [
    "filename:SKILL.md path:skills",
]

ALL_PLATFORMS = "claude-code,gemini,cursor,codex"

# Curated repos — crawled unconditionally regardless of topics/search.
#
# Two entry types:
#   type "multi"  (default) — list each dir in skills_dirs, treat subdirs as
#                             individual skills containing skill_file.
#   type "single" — fetch one skill_path file from the repo root.
CURATED_REPOS = [
    {
        "repo": "uipath/skills",
        "skills_dirs": ["skills"],
        "skill_file": "SKILL.md",
        "platform": ALL_PLATFORMS,
        "category": "cross-platform-skill",
        "tag_prefix": "cross-platform,skill,uipath",
    },
    {
        "repo": "microsoft/skills",
        "skills_dirs": [
            ".github/skills",
            ".github/plugins/azure-sdk-python/skills",
            ".github/plugins/azure-sdk-dotnet/skills",
            ".github/plugins/azure-sdk-typescript/skills",
            ".github/plugins/azure-sdk-java/skills",
            ".github/plugins/azure-sdk-rust/skills",
            ".github/plugins/azure-skills/skills",
            ".github/plugins/deep-wiki/skills",
            ".github/plugins/microsoft-foundry/skills",
        ],
        "skill_file": "SKILL.md",
        "platform": ALL_PLATFORMS,
        "category": "cross-platform-skill",
        "tag_prefix": "cross-platform,skill,microsoft",
    },
    {
        "repo": "eugeniughelbur/obsidian-second-brain",
        "type": "single",
        "skill_path": "SKILL.md",
        "platform": ALL_PLATFORMS,
        "category": "cross-platform-skill",
        "tag_prefix": "cross-platform,skill,obsidian",
    },
]

# Repository Search — repos tagged with Claude Code topics.
TOPIC_QUERIES = [
    "claude-code-skill",
    "claude-skill",
    "claude-code",
    "claude-agent",
]

# Sleep between every GitHub request to respect the strict Code Search rate limit.
REQUEST_DELAY = 2.0

# --- frontmatter parsing -----------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


def _parse_frontmatter(content: str, fallback_name: str) -> tuple[str, str]:
    """Return (name, description) parsed from YAML frontmatter, with fallbacks.

    Regex-based so we add no YAML dependency. If no frontmatter is present the
    name falls back to the filename (without .md) and the description to the
    first non-empty content line.
    """
    name = ""
    description = ""

    m = _FRONTMATTER_RE.match(content)
    if m:
        block = m.group(1)
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            kv = re.match(r"([A-Za-z_][\w-]*)\s*:\s*(.*)$", stripped)
            if not kv:
                continue
            key = kv.group(1).strip().lower()
            value = kv.group(2).strip().strip("'\"")
            if key == "name" and value:
                name = value
            elif key == "description" and value:
                description = value
        body = content[m.end():]
    else:
        body = content

    if not name:
        name = fallback_name
    if not description:
        for line in body.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                description = stripped[:300]
                break

    return name, description


# --- GitHub requests ---------------------------------------------------------

def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "skill-finder/0.1"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def _parse_github_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# Cache repo meta (stars/forks/pushed_at) to avoid re-fetching the same repo.
_repo_meta_cache: dict[str, dict] = {}


async def _get_repo_meta(client, repo_full_name: str) -> dict:
    if repo_full_name not in _repo_meta_cache:
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo_full_name}",
                headers=_headers(), timeout=15.0
            )
            _repo_meta_cache[repo_full_name] = resp.json() if resp.status_code == 200 else {}
        except Exception:
            _repo_meta_cache[repo_full_name] = {}
        await asyncio.sleep(REQUEST_DELAY)
    return _repo_meta_cache[repo_full_name]


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _code_search(client: httpx.AsyncClient, query: str, per_page: int = 30) -> list[dict]:
    resp = await client.get(
        f"{GITHUB_API}/search/code",
        params={"q": query, "per_page": per_page},
        headers=_headers(),
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _repo_search(client: httpx.AsyncClient, topic: str, per_page: int = 30) -> list[dict]:
    resp = await client.get(
        f"{GITHUB_API}/search/repositories",
        params={"q": f"topic:{topic}", "per_page": per_page, "sort": "stars"},
        headers=_headers(),
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


@retry(
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
)
async def _fetch_raw(client: httpx.AsyncClient, download_url: str) -> str:
    resp = await client.get(download_url, headers=_headers(), timeout=20.0)
    resp.raise_for_status()
    return resp.text


# --- crawl helpers -----------------------------------------------------------

async def _crawl_code_query(
    client: httpx.AsyncClient,
    db: AsyncSession,
    query: str,
    category: str = "claude-code-skill",
    platform: str = "claude-code",
    tag_prefix: str = "claude-code,skill",
):
    try:
        items = await _code_search(client, query)
    except Exception as e:
        print(f"[github_crawler] code query={query!r} error: {e}")
        return
    await asyncio.sleep(REQUEST_DELAY)

    for item in items:
        html_url = item.get("html_url") or ""
        if not html_url:
            continue

        existing = await db.execute(select(Skill).where(Skill.source_url == html_url))
        if existing.scalar_one_or_none():
            continue  # already indexed

        repo = item.get("repository") or {}
        repo_name = repo.get("full_name") or repo.get("name") or ""
        file_name = item.get("name") or "skill.md"
        fallback_name = file_name[:-3] if file_name.endswith(".md") else file_name

        # Build a raw download URL from the html_url (blob -> raw) since the
        # Code Search item doesn't include download_url directly.
        download_url = (
            html_url
            .replace("https://github.com/", "https://raw.githubusercontent.com/")
            .replace("/blob/", "/")
        )

        try:
            content = await _fetch_raw(client, download_url)
        except Exception as e:
            print(f"[github_crawler] fetch {download_url} error: {e}")
            await asyncio.sleep(REQUEST_DELAY)
            continue
        await asyncio.sleep(REQUEST_DELAY)

        name, description = _parse_frontmatter(content, fallback_name)

        meta = await _get_repo_meta(client, repo_name) if repo_name else {}

        skill = Skill(
            name=name,
            description=description,
            source="github",
            source_url=html_url,
            category=category,
            tags=f"{tag_prefix},{repo_name}" if repo_name else tag_prefix,
            platform=platform,
            stars=meta.get("stargazers_count") or 0,
            forks=meta.get("forks_count") or 0,
            last_pushed=_parse_github_date(meta.get("pushed_at")),
        )
        db.add(skill)

    await db.commit()


async def _crawl_topic_query(client: httpx.AsyncClient, db: AsyncSession, topic: str):
    try:
        items = await _repo_search(client, topic)
    except Exception as e:
        print(f"[github_crawler] topic={topic!r} error: {e}")
        return
    await asyncio.sleep(REQUEST_DELAY)

    for item in items:
        html_url = item.get("html_url") or ""
        if not html_url:
            continue

        existing = await db.execute(select(Skill).where(Skill.source_url == html_url))
        if existing.scalar_one_or_none():
            continue  # already indexed

        repo_name = item.get("full_name") or item.get("name") or ""
        skill = Skill(
            name=repo_name or item.get("name") or "",
            description=item.get("description") or "",
            source="github",
            source_url=html_url,
            category="claude-code-skill",
            tags=f"claude-code,skill,{repo_name}" if repo_name else "claude-code,skill",
            platform="claude-code",
            stars=item.get("stargazers_count") or 0,
            forks=item.get("forks_count") or 0,
            last_pushed=_parse_github_date(item.get("pushed_at")),
        )
        db.add(skill)

    await db.commit()


async def _crawl_curated_repo(client: httpx.AsyncClient, db: AsyncSession, entry: dict):
    """Fetch skill files from a known repo using the Contents API.

    Supports two modes:
      multi  (default) — each dir in skills_dirs is listed; subdirectories are
                         treated as individual skills containing skill_file.
      single           — fetch one skill_path file directly from the repo root.
    """
    repo = entry["repo"]
    platform = entry.get("platform", "claude-code")
    category = entry.get("category", "cross-platform-skill")
    tag_prefix = entry.get("tag_prefix", f"cross-platform,skill,{repo.split('/')[0]}")

    meta = await _get_repo_meta(client, repo)
    repo_stars = meta.get("stargazers_count") or 0
    repo_forks = meta.get("forks_count") or 0
    repo_pushed = _parse_github_date(meta.get("pushed_at"))

    if entry.get("type") == "single":
        skill_path = entry["skill_path"]
        html_url = f"https://github.com/{repo}/blob/main/{skill_path}"
        existing = await db.execute(select(Skill).where(Skill.source_url == html_url))
        if existing.scalar_one_or_none():
            print(f"[github_crawler] curated {repo}: already indexed")
            return
        raw_url = f"https://raw.githubusercontent.com/{repo}/main/{skill_path}"
        try:
            content = await _fetch_raw(client, raw_url)
        except Exception as e:
            print(f"[github_crawler] curated single {raw_url} error: {e}")
            return
        await asyncio.sleep(REQUEST_DELAY)
        fallback = repo.split("/")[1]
        name, description = _parse_frontmatter(content, fallback)
        db.add(Skill(name=name, description=description, source="github",
                     source_url=html_url, category=category,
                     tags=f"{tag_prefix},{fallback}", platform=platform,
                     stars=repo_stars, forks=repo_forks, last_pushed=repo_pushed))
        await db.commit()
        print(f"[github_crawler] curated {repo}: indexed 1 skill")
        return

    # multi mode
    skill_file = entry.get("skill_file", "SKILL.md")
    skills_dirs = entry.get("skills_dirs") or [entry.get("skills_dir", "skills")]
    total = 0

    for skills_dir in skills_dirs:
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/contents/{skills_dir}",
                headers=_headers(), timeout=20.0,
            )
            resp.raise_for_status()
            dir_entries = resp.json()
        except Exception as e:
            print(f"[github_crawler] curated {repo}/{skills_dir} error: {e}")
            await asyncio.sleep(REQUEST_DELAY)
            continue
        await asyncio.sleep(REQUEST_DELAY)

        dirs = [e for e in dir_entries if isinstance(e, dict) and e.get("type") == "dir"]
        for d in dirs:
            folder_name = d.get("name") or ""
            html_url = f"https://github.com/{repo}/blob/main/{skills_dir}/{folder_name}/{skill_file}"
            existing = await db.execute(select(Skill).where(Skill.source_url == html_url))
            if existing.scalar_one_or_none():
                continue
            raw_url = f"https://raw.githubusercontent.com/{repo}/main/{skills_dir}/{folder_name}/{skill_file}"
            try:
                content = await _fetch_raw(client, raw_url)
            except Exception as e:
                print(f"[github_crawler] curated fetch {raw_url} error: {e}")
                await asyncio.sleep(REQUEST_DELAY)
                continue
            await asyncio.sleep(REQUEST_DELAY)
            name, description = _parse_frontmatter(content, folder_name)
            db.add(Skill(name=name, description=description, source="github",
                         source_url=html_url, category=category,
                         tags=f"{tag_prefix},{folder_name}", platform=platform,
                         stars=repo_stars, forks=repo_forks, last_pushed=repo_pushed))
            total += 1

    await db.commit()
    print(f"[github_crawler] curated {repo}: indexed {total} skills")


async def crawl_github(db: AsyncSession):
    """Discover Claude Code skills on GitHub and upsert them into the DB."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for query in CODE_QUERIES:
            await _crawl_code_query(client, db, query)
        for query in CROSS_PLATFORM_QUERIES:
            await _crawl_code_query(
                client, db, query,
                category="cross-platform-skill",
                platform=ALL_PLATFORMS,
                tag_prefix="cross-platform,skill",
            )
        for topic in TOPIC_QUERIES:
            await _crawl_topic_query(client, db, topic)
        for entry in CURATED_REPOS:
            await _crawl_curated_repo(client, db, entry)
    _repo_meta_cache.clear()
    print("[github_crawler] done")

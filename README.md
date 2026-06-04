# skill-finder

Standalone web app: พิมพ์ลักษณะของ skill ที่อยากได้ → ระบบค้นหาด้วย semantic search
และแนะนำ skill ใหม่ที่คล้ายกับสิ่งที่เคยสนใจ (proactive recommendation)

## Requirements (ตัดสินใจแล้ว)

| ด้าน | การตัดสินใจ |
|---|---|
| แหล่งข้อมูล | GitHub Search API + VS Code Marketplace + web |
| วิธี match | Semantic / embedding search (vector similarity via FAISS) |
| รูปแบบส่งมอบ | Standalone web app |

## Stack

- **Backend**: Python 3.11–3.13 / FastAPI + uvicorn (3.13 recommended — `faiss-cpu` + `sentence-transformers` ship prebuilt wheels for it; 3.14 may lack wheels)
- **Storage**: SQLite (async via aiosqlite + SQLAlchemy 2)
- **Vector search**: FAISS (in-process) + sentence-transformers (`all-MiniLM-L6-v2`, runs locally, no API key needed)
  - Switchable to OpenAI `text-embedding-3-small` via `EMBEDDING_BACKEND=openai`
- **Crawler**: httpx + tenacity (retry / rate-limit handling)
- **Frontend**: Vanilla HTML/JS (served by FastAPI)

## Quick start

```bash
# 1. Create venv
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install deps
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# (edit .env — add GITHUB_TOKEN to raise crawl rate limit)

# 4. Crawl sources + build index (first time, or to refresh)
python scripts/crawl_and_index.py

# 5. Start server
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Open http://localhost:8000
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/search?q=...` | Semantic search |
| GET | `/api/recommendations` | Proactive recommendations from interest history |
| GET | `/api/skills/{id}` | Skill detail |
| POST | `/admin/crawl` | Trigger background crawl |
| POST | `/admin/rebuild-index` | Rebuild FAISS index |
| GET | `/health` | Health check |

## Architecture

```
user query
    │
    ▼
FastAPI /api/search
    │
    ├─ embed query (sentence-transformers local)
    ├─ FAISS nearest-neighbor search
    ├─ fetch Skill rows from SQLite
    ├─ save UserInterest history
    └─ get_recommendations() from past interests
            │
            └─ returns fresh skills not yet seen
```

## Project status

`developed` — requirements + design spec implemented. Backend (search, recommendations, admin,
crawler, FAISS index) and frontend (full design-spec UI) complete; seeded with 210 skills from
GitHub + VS Code Marketplace.

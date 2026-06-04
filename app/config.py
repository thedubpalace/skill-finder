from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "skill-finder"
    db_path: str = "data/skills.db"
    embedding_backend: str = "local"          # "local" | "openai"
    embedding_model: str = "all-MiniLM-L6-v2" # used when backend=local
    openai_api_key: str = ""                   # used when backend=openai
    github_token: str = ""                     # for GitHub crawler (optional but raises rate limit)
    youtube_api_key: str = ""                  # for YouTube crawler (optional; skipped if empty)
    index_path: str = "data/faiss.index"
    host: str = "127.0.0.1"
    port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

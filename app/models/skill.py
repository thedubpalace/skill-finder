from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Index
from sqlalchemy.sql import func
from app.database import Base


class Skill(Base):
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, default="")
    source = Column(String(64), nullable=False)          # "github" | "marketplace" | "web"
    source_url = Column(String(512), default="")
    category = Column(String(128), default="")
    tags = Column(Text, default="")                      # comma-separated
    platform = Column(Text, default="")                  # comma-separated: "claude-code", "gemini", "cursor", "codex"
    embedding_id = Column(Integer, nullable=True)        # row index in FAISS index
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    last_pushed = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (Index("ix_skills_source", "source"),)


class UserInterest(Base):
    __tablename__ = "user_interests"

    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text, nullable=False)                 # raw query the user typed
    top_skill_ids = Column(Text, default="")             # comma-separated skill IDs returned
    created_at = Column(DateTime(timezone=True), server_default=func.now())

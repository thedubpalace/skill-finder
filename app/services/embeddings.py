"""
Embedding service — supports two backends:
  - "local"  : sentence-transformers (all-MiniLM-L6-v2, runs on CPU, no API key)
  - "openai" : OpenAI text-embedding-3-small (needs OPENAI_API_KEY in .env)

Switch via EMBEDDING_BACKEND env var (default: local).
"""
from __future__ import annotations
import numpy as np
from app.config import settings

_model = None


def _load_model():
    global _model
    if _model is not None:
        return _model
    if settings.embedding_backend == "local":
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.embedding_model)
    else:
        import openai
        openai.api_key = settings.openai_api_key
        _model = "openai"
    return _model


def embed(texts: list[str]) -> np.ndarray:
    """Return float32 numpy array of shape (len(texts), dim)."""
    model = _load_model()
    if settings.embedding_backend == "local":
        return model.encode(texts, convert_to_numpy=True, show_progress_bar=False).astype("float32")
    else:
        import openai
        response = openai.embeddings.create(input=texts, model="text-embedding-3-small")
        vecs = [d.embedding for d in response.data]
        return np.array(vecs, dtype="float32")

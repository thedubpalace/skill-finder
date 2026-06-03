"""
FAISS index manager — build, save, load, and search.
The index maps embedding_id (row) → skill.id (stored in a parallel list).
"""
from __future__ import annotations
import os
import json
import faiss
import numpy as np
from pathlib import Path
from app.config import settings
from app.services.embeddings import embed

_index: faiss.IndexFlatIP | None = None
_id_map: list[int] = []          # position i → skill.id in DB


def _index_path() -> Path:
    return Path(settings.index_path)


def load_index():
    global _index, _id_map
    p = _index_path()
    map_p = p.with_suffix(".ids.json")
    if p.exists() and map_p.exists():
        _index = faiss.read_index(str(p))
        _id_map = json.loads(map_p.read_text())
    else:
        _index = None
        _id_map = []


def build_index(skill_ids: list[int], skill_texts: list[str]):
    """Rebuild index from scratch given parallel lists of DB ids and text."""
    global _index, _id_map
    vecs = embed(skill_texts)
    faiss.normalize_L2(vecs)
    dim = vecs.shape[1]
    _index = faiss.IndexFlatIP(dim)
    _index.add(vecs)
    _id_map = skill_ids
    _save_index()


def _save_index():
    p = _index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(_index, str(p))
    p.with_suffix(".ids.json").write_text(json.dumps(_id_map))


def search(query: str, top_k: int = 10) -> list[tuple[int, float]]:
    """Return list of (skill_id, score) sorted by descending similarity."""
    if _index is None or _index.ntotal == 0:
        return []
    vec = embed([query])
    faiss.normalize_L2(vec)
    scores, indices = _index.search(vec, top_k)
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue
        results.append((_id_map[idx], float(score)))
    return results

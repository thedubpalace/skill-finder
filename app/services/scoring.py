"""Composite rating = weighted semantic + popularity + freshness."""
from __future__ import annotations
import math
from datetime import datetime, timezone

W_SEMANTIC   = 0.60
W_POPULARITY = 0.25
W_FRESHNESS  = 0.15
STARS_REF    = 1000      # stars ที่ได้ popularity_score = 1.0 (log scale)
HALF_LIFE    = 365       # freshness half-life in days


def popularity_score(stars: int, forks: int) -> float:
    raw = (stars or 0) + 0.5 * (forks or 0)
    return min(1.0, math.log1p(raw) / math.log1p(STARS_REF))


def freshness_score(last_pushed: datetime | None) -> float:
    if not last_pushed:
        return 0.3
    now = datetime.now(timezone.utc)
    lp = last_pushed if last_pushed.tzinfo else last_pushed.replace(tzinfo=timezone.utc)
    days = max(0, (now - lp).days)
    return math.exp(-days * math.log(2) / HALF_LIFE)


def composite_rating(semantic: float, stars: int, forks: int,
                     last_pushed: datetime | None) -> float:
    return round(
        W_SEMANTIC * semantic
        + W_POPULARITY * popularity_score(stars, forks)
        + W_FRESHNESS  * freshness_score(last_pushed),
        4
    )

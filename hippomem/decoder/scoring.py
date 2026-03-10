"""
Combined scoring for event retrieval: semantic + relevance + recency.

Scoring formula (defaults match MemoryConfig retrieval weight fields):
    score = w_sem * cosine_similarity + w_rel * relevance_score + w_rec * recency_bias

Default weights are imported from config to keep a single source of truth.
Callers can override per-query by passing explicit w_sem / w_rel / w_rec arguments.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

from hippomem.config import (
    DEFAULT_RETRIEVAL_SEMANTIC_WEIGHT as _DEFAULT_SEMANTIC_WEIGHT,
    DEFAULT_RETRIEVAL_RELEVANCE_WEIGHT as _DEFAULT_RELEVANCE_WEIGHT,
    DEFAULT_RETRIEVAL_RECENCY_WEIGHT as _DEFAULT_RECENCY_WEIGHT,
)


def _compute_recency_bias(last_updated: Optional[datetime]) -> float:
    """Recency bias: newer = higher. Decay over ~1 week."""
    now = datetime.now(timezone.utc)
    if last_updated is None:
        return 0.0
    delta = now - (last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc))
    hours = delta.total_seconds() / 3600
    return max(0, min(1, 1.0 - (hours / 168) * 0.5))


def score_engram_with_breakdown(
    semantic_similarity: float,
    relevance_score: float,
    last_updated: Optional[datetime],
    w_sem: float = _DEFAULT_SEMANTIC_WEIGHT,
    w_rel: float = _DEFAULT_RELEVANCE_WEIGHT,
    w_rec: float = _DEFAULT_RECENCY_WEIGHT,
    engram_id: Optional[str] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Combined score plus breakdown.
    Returns (combined_score, {semantic, relevance, recency, combined}).
    """
    recency_bias = _compute_recency_bias(last_updated)
    combined = w_sem * semantic_similarity + w_rel * relevance_score + w_rec * recency_bias

    breakdown = {
        "semantic": round(semantic_similarity, 4),
        "relevance": round(relevance_score, 4),
        "recency": round(recency_bias, 4),
        "combined": round(combined, 4),
    }
    if engram_id is not None:
        logger.debug(
            "score: engram=%s total=%.3f sem=%.3f rel=%.3f rec=%.3f",
            engram_id, combined,
            semantic_similarity, relevance_score, recency_bias,
        )
    return combined, breakdown


def score_event(
    semantic_similarity: float,
    relevance_score: float,
    last_updated: Optional[datetime],
    w_sem: float = _DEFAULT_SEMANTIC_WEIGHT,
    w_rel: float = _DEFAULT_RELEVANCE_WEIGHT,
    w_rec: float = _DEFAULT_RECENCY_WEIGHT,
) -> float:
    """
    Combined score: 0.5*semantic + 0.3*relevance + 0.2*recency_bias (defaults).

    Args:
        semantic_similarity: 0-1, cosine similarity between query and event
        relevance_score: 0-1, from Engram.relevance_score
        last_updated: When event was last touched (None = treat as old)

    Returns:
        Combined score 0-1
    """
    combined, _ = score_engram_with_breakdown(
        semantic_similarity, relevance_score, last_updated, w_sem, w_rel, w_rec
    )
    return combined

"""
Real-time embedding for immediate FAISS updates after engram creation/changes.
"""
import hashlib
import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from hippomem.models.engram import Engram
from hippomem.infra.embeddings import EmbeddingService
from hippomem.infra.vector.faiss_service import FAISSService

logger = logging.getLogger(__name__)


def compute_content_hash(core_intent: str, updates: List[str]) -> str:
    """Compute SHA256 content hash for change detection."""
    content = f"{core_intent} {' '.join(updates or [])}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def embed_engram(
    engram_id: str,
    core_intent: str,
    updates: List[str],
    embedding_svc: EmbeddingService,
) -> Optional[Tuple[List[float], str]]:
    """Generate embedding for engram content. Returns (vector, content_hash) or None on failure."""
    content = f"{core_intent} {' '.join(updates or [])}"
    try:
        vector = embedding_svc.embed(content)
        content_hash = compute_content_hash(core_intent, updates)
        return (vector, content_hash)
    except Exception as e:
        logger.warning("Embedding failed for engram %s: %s", engram_id, e)
        return None


def add_to_faiss_realtime(
    user_id: str,
    engram_id: str,
    vector: List[float],
    content_hash: str,
    faiss_svc: FAISSService,
    index,
    db: Session,
) -> None:
    """Add/refresh embedding in FAISS index and update Engram content_hash."""
    existing = db.query(Engram).filter(
        Engram.user_id == user_id,
        Engram.engram_id == engram_id,
    ).first()
    remove_if_exists = existing is not None
    op = "refresh" if remove_if_exists else "add"
    logger.debug("faiss_%s: engram=%s hash=%s", op, engram_id[:8], content_hash)
    faiss_svc.add_vector(engram_id, vector, index, remove_if_exists=remove_if_exists, user_id=user_id)
    if existing:
        existing.content_hash = content_hash
    db.flush()

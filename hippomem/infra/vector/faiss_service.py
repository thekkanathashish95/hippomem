"""
FAISS Service — per-user vector index with IndexIDMap2.
"""
import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import faiss
from sqlalchemy.orm import Session

from hippomem.models.engram import Engram

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536  # text-embedding-3-small


def _event_uuid_to_faiss_id(engram_id: str) -> np.int64:
    """Convert engram_id to int64 for FAISS. Deterministic."""
    clean = engram_id.replace("-", "")[:16]
    try:
        return np.int64(int(clean, 16) & 0x7FFF_FFFF_FFFF_FFFF)
    except ValueError:
        h = hashlib.sha256(engram_id.encode()).digest()
        return np.int64(int.from_bytes(h[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF)


def _normalize(v: np.ndarray) -> np.ndarray:
    """L2 normalize for cosine via inner product."""
    if v.ndim == 1:
        v = v.reshape(1, -1)
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    norm = np.where(norm == 0, 1.0, norm)
    return (v.astype(np.float32) / norm).squeeze()


class FAISSService:
    """Per-user FAISS index management with IndexIDMap2."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir or ".hippomem/vectors")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _index_path(self, user_id: str) -> Path:
        safe = re.sub(r"[/\\:]+", "_", user_id)
        return self.base_dir / f"{safe}.index"

    def load_index(self, user_id: str) -> Optional[faiss.Index]:
        """Load index from disk. Returns None if not found."""
        path = self._index_path(user_id)
        if not path.exists():
            return None
        try:
            return faiss.read_index(str(path))
        except Exception as e:
            logger.warning("Failed to load FAISS index for user %s: %s", user_id, e)
            return None

    def save_index(self, user_id: str, index: faiss.Index) -> None:
        """Persist index to disk. Atomic write (temp + rename)."""
        path = self._index_path(user_id)
        tmp = path.with_suffix(".index.tmp")
        try:
            faiss.write_index(index, str(tmp))
            tmp.replace(path)
        except Exception as e:
            logger.error("failed to save index user=%s: %s", user_id, e)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def get_or_create_index(self, user_id: str) -> faiss.Index:
        """Load existing or create empty IndexIDMap2(IndexFlatIP(dim))."""
        index = self.load_index(user_id)
        if index is not None:
            return index
        logger.info("index not found for user=%s, initializing empty", user_id)
        base = faiss.IndexFlatIP(EMBEDDING_DIM)
        return faiss.IndexIDMap2(base)

    def add_vector(
        self,
        event_uuid: str,
        vector: List[float],
        index: faiss.Index,
        remove_if_exists: bool = False,
        user_id: Optional[str] = None,
    ) -> None:
        """Add vector to index. Optionally remove existing entry first."""
        faiss_id = _event_uuid_to_faiss_id(event_uuid)
        if remove_if_exists:
            try:
                index.remove_ids(np.array([faiss_id], dtype=np.int64))
            except Exception as e:
                logger.debug("remove_ids (pre-add) skipped for %s: %s", event_uuid, e)
        vec = np.array([vector], dtype=np.float32)
        vec_norm = _normalize(vec)
        if vec_norm.ndim == 1:
            vec_norm = vec_norm.reshape(1, -1)
        index.add_with_ids(vec_norm, np.array([faiss_id], dtype=np.int64))
        if user_id is not None:
            logger.debug("add: user=%s engram=%s", user_id, event_uuid)

    def remove_vector(self, event_uuid: str, index: faiss.Index) -> None:
        """Remove vector by event_uuid. Idempotent."""
        faiss_id = _event_uuid_to_faiss_id(event_uuid)
        try:
            index.remove_ids(np.array([faiss_id], dtype=np.int64))
        except Exception as e:
            logger.debug("remove_ids skipped for %s: %s", event_uuid, e)

    def get_vector(self, event_uuid: str, index: faiss.Index) -> Optional[List[float]]:
        """Reconstruct stored vector by event_uuid. Returns None if not found."""
        if index is None or index.ntotal == 0:
            return None
        faiss_id = _event_uuid_to_faiss_id(event_uuid)
        try:
            vec = index.reconstruct(int(faiss_id))
            return vec.astype(np.float32).tolist()
        except Exception:
            return None

    def search(
        self,
        query_vector: List[float],
        k: int,
        index: faiss.Index,
        exclude_event_uuid: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Tuple[np.int64, float]]:
        """Return [(faiss_id, similarity), ...] for top k results."""
        if index.ntotal == 0:
            if user_id is not None:
                logger.debug("search: user=%s k=%d hits=0", user_id, k)
            return []
        vec = np.array([query_vector], dtype=np.float32)
        vec_norm = _normalize(vec)
        if vec_norm.ndim == 1:
            vec_norm = vec_norm.reshape(1, -1)
        search_k = min(k + 1, index.ntotal)
        distances, ids = index.search(vec_norm, search_k)
        exclude_id = _event_uuid_to_faiss_id(exclude_event_uuid) if exclude_event_uuid else None
        results = []
        for dist, idx in zip(distances[0], ids[0]):
            if idx == -1:
                continue
            if exclude_id is not None and idx == exclude_id:
                continue
            results.append((np.int64(idx), float(dist)))
        if user_id is not None:
            logger.debug("search: user=%s k=%d hits=%d", user_id, k, len(results))
        return results[:k]

    def build_id_to_uuid_map(self, user_id: str, db: Session) -> Dict[np.int64, str]:
        """Build faiss_id → engram_id map from Engram for user."""
        rows = db.query(Engram).filter(Engram.user_id == user_id).all()
        return {_event_uuid_to_faiss_id(r.engram_id): r.engram_id for r in rows}

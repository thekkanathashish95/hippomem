"""
C2: Local Scan - Scores active + dormant events and returns top 3 active + top 2 dormant.
Uses FAISS reconstruct for event embeddings when available, embed() as fallback.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, TYPE_CHECKING

import numpy as np
from sqlalchemy.orm import Session

from hippomem.infra.embeddings import EmbeddingService
from hippomem.models.engram import Engram
from hippomem.decoder.scoring import score_engram_with_breakdown

if TYPE_CHECKING:
    from hippomem.infra.vector.faiss_service import FAISSService

logger = logging.getLogger(__name__)


@dataclass
class LocalScanResult:
    """Result of C2 local scan."""

    events: List[Dict[str, Any]] = field(default_factory=list)
    high_confidence: bool = False
    score_breakdowns: List[Dict[str, Any]] = field(default_factory=list)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors. Returns 0-1 for non-negative embeddings."""
    a = np.asarray(a, dtype=np.float32).flatten()
    b = np.asarray(b, dtype=np.float32).flatten()
    dot = np.dot(a, b)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    sim = dot / (na * nb)
    return float(max(0, min(1, (sim + 1) / 2)))  # Map [-1,1] to [0,1]


class LocalScanRanker:
    """C2: Score active + dormant, return top 3 active + top 2 dormant."""

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        faiss_service: Optional["FAISSService"] = None,
    ) -> None:
        self.embedding_service = embedding_service
        if faiss_service is None:
            from hippomem.infra.vector.faiss_service import FAISSService
            faiss_service = FAISSService()
        self.faiss_service: "FAISSService" = faiss_service

    def _get_event_embeddings(
        self,
        events: List[Dict[str, Any]],
        user_id: str,
        fallback_zero: np.ndarray,
    ) -> List[List[float]]:
        """
        Get embeddings via FAISS reconstruct when available, embed() as fallback.
        Returns list of vectors in same order as events.
        """
        index = self.faiss_service.load_index(user_id)
        result: List[tuple] = []
        need_embed: List[tuple] = []
        for i, e in enumerate(events):
            uuid_val = e.get("event_uuid") or e.get("event_id")
            if uuid_val and index:
                vec = self.faiss_service.get_vector(uuid_val, index)
                if vec is not None:
                    result.append((i, vec))
                    continue
            text = e.get("core_intent", "") or " "
            need_embed.append((i, text))
        combined: Dict[int, List[float]] = dict(result)
        if need_embed and self.embedding_service:
            indices, texts = zip(*[(idx, t) for idx, t in need_embed])
            try:
                embedded = self.embedding_service.embed_batch(list(texts))
            except Exception as e:
                logger.warning(
                    "Batch embedding failed for %d events, using zero vectors: %s",
                    len(texts), e,
                )
                embedded = [fallback_zero.tolist()] * len(indices)
            for j, idx in enumerate(indices):
                combined[idx] = embedded[j] if j < len(embedded) else fallback_zero.tolist()
        return [combined.get(i, fallback_zero.tolist()) for i in range(len(events))]

    def scan_and_rank(
        self,
        query: str,
        conversation_window: str,
        active_events: List[Dict[str, Any]],
        dormant_events: List[Dict[str, Any]],
        user_id: str,
        db: Session,
        threshold: float = 0.6,
        top_active: int = 3,
        top_dormant: int = 2,
        w_sem: float = 0.5,
        w_rel: float = 0.3,
        w_rec: float = 0.2,
    ) -> LocalScanResult:
        """
        Score active + dormant events, return top 3 active + top 2 dormant.
        Uses: w_sem*semantic + w_rel*relevance + w_rec*recency.
        """
        if not self.embedding_service:
            return LocalScanResult(events=[], high_confidence=False)

        search_input = f"{query}\n\n{conversation_window}".strip() if conversation_window else query

        try:
            query_embedding = self.embedding_service.embed(search_input)
        except Exception as e:
            logger.warning("Local scan embedding failed: %s", e)
            return LocalScanResult(events=[], high_confidence=False)

        query_vec = np.array(query_embedding, dtype=np.float32)

        all_candidates = active_events + dormant_events
        uuids = [e.get("event_uuid") or e.get("event_id") for e in all_candidates]
        try:
            rows = db.query(Engram).filter(
                Engram.user_id == user_id,
                Engram.engram_id.in_([u for u in uuids if u]),
            ).all()
            uuid_to_row = {r.engram_id: r for r in rows}
        except Exception as e:
            logger.warning("Local scan DB enrich failed for user %s: %s", user_id, e)
            uuid_to_row = {}
        for i, event in enumerate(all_candidates):
            row = uuid_to_row.get(uuids[i]) if uuids[i] else None
            event["_relevance_score"] = float(row.relevance_score or 1.0) if row else 1.0
            event["_last_updated"] = row.last_updated_at if row else None

        embeddings = self._get_event_embeddings(all_candidates, user_id, np.zeros_like(query_vec))

        scored_active: List[tuple] = []
        for i, e in enumerate(active_events):
            emb = embeddings[i] if i < len(embeddings) else query_vec * 0
            sem = _cosine_similarity(query_vec, np.array(emb, dtype=np.float32))
            rel = e.get("_relevance_score", 1.0)
            lu = e.get("_last_updated")
            eid = e.get("event_uuid") or e.get("event_id")
            score, breakdown = score_engram_with_breakdown(
                sem, rel, lu, w_sem, w_rel, w_rec, engram_id=eid,
            )
            scored_active.append((score, e, breakdown))

        off = len(active_events)
        scored_dormant: List[tuple] = []
        for j, e in enumerate(dormant_events):
            idx = off + j
            emb = embeddings[idx] if idx < len(embeddings) else query_vec * 0
            sem = _cosine_similarity(query_vec, np.array(emb, dtype=np.float32))
            rel = e.get("_relevance_score", 1.0)
            lu = e.get("_last_updated")
            eid = e.get("event_uuid") or e.get("event_id")
            score, breakdown = score_engram_with_breakdown(
                sem, rel, lu, w_sem, w_rel, w_rec, engram_id=eid,
            )
            scored_dormant.append((score, e, breakdown))

        scored_active.sort(key=lambda x: x[0], reverse=True)
        scored_dormant.sort(key=lambda x: x[0], reverse=True)

        top_a = [e for _, e, _ in scored_active[:top_active]]
        top_d = [e for _, e, _ in scored_dormant[:top_dormant]]
        breakdowns_a = [b for _, _, b in scored_active[:top_active]]
        breakdowns_d = [b for _, _, b in scored_dormant[:top_dormant]]

        for e in top_a + top_d:
            e.pop("_relevance_score", None)
            e.pop("_last_updated", None)

        all_events = top_a + top_d
        score_breakdowns = breakdowns_a + breakdowns_d
        top_score = (
            max(
                (scored_active[0][0] if scored_active else 0),
                (scored_dormant[0][0] if scored_dormant else 0),
            )
            if (scored_active or scored_dormant)
            else 0
        )
        high_conf = top_score >= threshold
        logger.debug(
            "scan: active=%d dormant=%d → top_active=%d top_dormant=%d high_confidence=%s",
            len(active_events), len(dormant_events),
            len(top_a), len(top_d), high_conf,
        )

        return LocalScanResult(
            events=all_events,
            high_confidence=high_conf,
            score_breakdowns=score_breakdowns,
        )

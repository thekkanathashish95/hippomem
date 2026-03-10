"""
Real-time link processing for immediate graph updates after engram creation/changes.
"""
import logging
from typing import List, Set, Tuple
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from hippomem.models.engram_link import EngramLink, LinkKind
from hippomem.infra.vector.faiss_service import FAISSService
from hippomem.infra.graph.edges import upsert_link
from hippomem.config import (
    DEFAULT_EDGE_SIMILARITY_ALPHA as ALPHA,
    DEFAULT_EDGE_TRIADIC_BONUS as TRIADIC_BONUS,
    DEFAULT_EDGE_TOP_K as TOP_K,
    DEFAULT_EDGE_MIN_SIMILARITY as MIN_SIMILARITY,
)


def top_k_similar(
    vector: List[float],
    user_id: str,
    exclude_id: str,
    top_k: int,
    db: Session,
    faiss_svc: FAISSService,
    index,
) -> List[Tuple[str, float]]:
    """Find top-k similar engrams via FAISS search."""
    results = faiss_svc.search(vector, top_k + 1, index, exclude_event_uuid=exclude_id)
    logger.debug("faiss_search: engram=%s raw_results=%d top_k=%d min_sim=%.3f", exclude_id, len(results), top_k, MIN_SIMILARITY)
    id_to_uuid = faiss_svc.build_id_to_uuid_map(user_id, db)
    neighbors = []
    for faiss_id, score in results:
        if score < MIN_SIMILARITY:
            logger.debug("faiss_search: dropped faiss_id=%s score=%.4f (below min_sim)", faiss_id, score)
            continue
        uuid_val = id_to_uuid.get(faiss_id)
        if uuid_val and uuid_val != exclude_id:
            neighbors.append((uuid_val, score))
    neighbors = neighbors[:top_k]
    logger.debug("faiss_search: engram=%s neighbors_found=%d %s", exclude_id, len(neighbors), [(uid[:8], round(s, 4)) for uid, s in neighbors])
    return neighbors


def process_links_realtime(
    user_id: str,
    engram_id: str,
    vector: List[float],
    db: Session,
    faiss_svc: FAISSService,
    index,
    processed_pairs: Set[Tuple[str, str]],
) -> List[str]:
    """
    Create similarity links + triadic closure for a new/updated engram.
    Returns list of neighbor engram IDs.
    """
    neighbors = top_k_similar(vector, user_id, engram_id, TOP_K, db, faiss_svc, index)
    neighbor_ids: List[str] = []

    for neighbor_id, score in neighbors:
        pair = tuple(sorted([engram_id, neighbor_id]))
        if pair not in processed_pairs:
            logger.debug("similarity_link: %s↔%s score=%.4f", engram_id[:8], neighbor_id[:8], score)
            upsert_link(user_id, engram_id, neighbor_id, LinkKind.SIMILARITY, ALPHA, db)
            processed_pairs.add(pair)
        neighbor_ids.append(neighbor_id)

    # Triadic closure: strengthen links between neighbors that already know each other
    triadic_count = 0
    for i, a in enumerate(neighbor_ids):
        for b in neighbor_ids[i + 1:]:
            pair = tuple(sorted([a, b]))
            if pair not in processed_pairs:
                x, y = pair
                existing = db.query(EngramLink).filter(
                    EngramLink.user_id == user_id,
                    EngramLink.source_id == x,
                    EngramLink.target_id == y,
                    EngramLink.link_kind == LinkKind.SIMILARITY.value,
                ).first()
                if existing:
                    logger.debug("triadic_closure: %s↔%s (via %s) weight=%.3f+%.3f", a[:8], b[:8], engram_id[:8], existing.weight, TRIADIC_BONUS)
                    upsert_link(user_id, a, b, LinkKind.TRIADIC, TRIADIC_BONUS, db)
                    processed_pairs.add(pair)
                    triadic_count += 1

    logger.debug("process_links_realtime: engram=%s similarity_links=%d triadic_closures=%d", engram_id[:8], len(neighbor_ids), triadic_count)
    db.flush()
    return neighbor_ids

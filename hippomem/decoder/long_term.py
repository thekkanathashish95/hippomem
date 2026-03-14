"""
C3: Long-Term Retrieval - Hybrid FAISS + BM25 search with RRF fusion and graph expansion.
"""
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, TYPE_CHECKING

from sqlalchemy.orm import Session

from hippomem.models.engram import Engram, EngramKind
from hippomem.infra.graph.queries import get_neighbors
from hippomem.decoder.scoring import score_engram_with_breakdown
from hippomem.infra.bm25 import BM25Retriever
from hippomem.config import (
    DEFAULT_RETRIEVAL_SEMANTIC_WEIGHT,
    DEFAULT_RETRIEVAL_RELEVANCE_WEIGHT,
    DEFAULT_RETRIEVAL_RECENCY_WEIGHT,
)

if TYPE_CHECKING:
    from hippomem.infra.vector.faiss_service import FAISSService
    from hippomem.infra.embeddings import EmbeddingService

logger = logging.getLogger(__name__)

_EPISODIC_KINDS = {EngramKind.EPISODE.value, EngramKind.SUMMARY.value}


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity mapped to [0, 1] for non-negative embedding spaces."""
    a = np.asarray(a, dtype=np.float32).flatten()
    b = np.asarray(b, dtype=np.float32).flatten()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    sim = np.dot(a, b) / (na * nb)
    return float(max(0.0, min(1.0, (sim + 1) / 2)))


def _rrf_merge(
    faiss_uuids: List[str],
    bm25_uuids: List[str],
    k: int = 60,
) -> List[str]:
    """
    Reciprocal Rank Fusion over two ranked lists.
    score(d) = Σ 1/(k + rank) where rank is 1-indexed.
    Returns merged list of uuids sorted by RRF score descending.
    """
    scores: Dict[str, float] = {}
    for rank, uuid in enumerate(faiss_uuids):
        scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (k + rank + 1)
    for rank, uuid in enumerate(bm25_uuids):
        scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (k + rank + 1)
    return [uuid for uuid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


@dataclass
class LongTermResult:
    """Result of C3 long-term retrieval."""

    events: List[Dict[str, Any]] = field(default_factory=list)
    graph_expanded: List[Dict[str, Any]] = field(default_factory=list)
    total_found: int = 0


class LongTermRetriever:
    """C3: Hybrid FAISS + BM25 retrieval, RRF fusion, graph expansion, composite scoring."""

    def __init__(
        self,
        embedding_service: Optional["EmbeddingService"] = None,
        faiss_service: Optional["FAISSService"] = None,
    ) -> None:
        self._embedding_service = embedding_service
        if faiss_service is None:
            from hippomem.infra.vector.faiss_service import FAISSService
            faiss_service = FAISSService()
        self.faiss_service: "FAISSService" = faiss_service
        self.bm25_retriever = BM25Retriever()

    @property
    def embedding_service(self) -> "EmbeddingService":
        if self._embedding_service is None:
            raise RuntimeError("EmbeddingService not provided to LongTermRetriever")
        return self._embedding_service

    def retrieve(
        self,
        query: str,
        conversation_window: str,
        exclude_uuids: List[str],
        user_id: str,
        db: Session,
        top_k: int = 5,
        enable_graph_expansion: bool = True,
        graph_hops: int = 1,
        max_graph_events: int = 5,
        enable_bm25: bool = True,
        bm25_index_ttl_seconds: int = 300,
        rrf_k: int = 60,
        w_sem: float = DEFAULT_RETRIEVAL_SEMANTIC_WEIGHT,
        w_rel: float = DEFAULT_RETRIEVAL_RELEVANCE_WEIGHT,
        w_rec: float = DEFAULT_RETRIEVAL_RECENCY_WEIGHT,
    ) -> LongTermResult:
        """
        Hybrid FAISS + BM25 retrieval with RRF fusion, graph expansion, and composite scoring.

        Retrieval: FAISS (semantic) + BM25 (keyword) → merged via RRF.
        Scoring: w_sem*cosine + w_rel*relevance_score + w_rec*recency_bias (same as C2).
        Only episodic engrams (EPISODE, SUMMARY) returned — entities injected separately.
        """
        exclude = set(exclude_uuids or [])
        search_input = f"{query}\n\n{conversation_window}".strip() if conversation_window else query

        # ── Embed query ──────────────────────────────────────────────────────
        try:
            query_vec = np.asarray(self.embedding_service.embed(search_input), dtype=np.float32)
        except Exception as e:
            logger.warning("C3 embedding failed: %s", e)
            return LongTermResult()

        # ── FAISS search ─────────────────────────────────────────────────────
        index = self.faiss_service.load_index(user_id)
        if index is None or index.ntotal == 0:
            return LongTermResult()

        raw_results = self.faiss_service.search(query_vec, top_k * 2, index, user_id=user_id)
        id_to_uuid = self.faiss_service.build_id_to_uuid_map(user_id, db)

        faiss_uuids: List[str] = []
        faiss_uuid_to_score: Dict[str, float] = {}
        for faiss_id, score in raw_results:
            uuid_val = id_to_uuid.get(faiss_id)
            if uuid_val and uuid_val not in faiss_uuid_to_score:
                faiss_uuids.append(uuid_val)
                faiss_uuid_to_score[uuid_val] = float(score)

        # ── BM25 search ──────────────────────────────────────────────────────
        bm25_uuids: List[str] = []
        if enable_bm25:
            bm25_results = self.bm25_retriever.retrieve(
                query=search_input,
                user_id=user_id,
                db=db,
                top_k=top_k * 2,
                ttl_seconds=bm25_index_ttl_seconds,
            )
            bm25_uuids = [r["event_uuid"] for r in bm25_results]
            logger.debug("BM25: hits=%d", len(bm25_uuids))

        # ── RRF merge ────────────────────────────────────────────────────────
        merged_uuids = _rrf_merge(faiss_uuids, bm25_uuids, k=rrf_k)
        logger.debug(
            "C3 candidates: faiss=%d bm25=%d rrf_merged=%d",
            len(faiss_uuids), len(bm25_uuids), len(merged_uuids),
        )

        # ── Primary event collection ─────────────────────────────────────────
        primary_events: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for uuid_val in merged_uuids:
            if uuid_val in exclude or uuid_val in seen:
                continue
            seen.add(uuid_val)
            try:
                row = db.query(Engram).filter(
                    Engram.user_id == user_id,
                    Engram.engram_id == uuid_val,
                ).first()
            except Exception as e:
                logger.warning("C3 DB lookup failed for %s: %s", uuid_val, e)
                continue
            if row and row.core_intent and row.engram_kind in _EPISODIC_KINDS:
                sem = faiss_uuid_to_score.get(uuid_val, 0.0)
                composite, _ = score_engram_with_breakdown(
                    sem, row.relevance_score or 1.0, row.last_updated_at,
                    w_sem, w_rel, w_rec, engram_id=uuid_val,
                )
                primary_events.append({
                    "event_uuid": uuid_val,
                    "core_intent": row.core_intent,
                    "score": composite,
                    "source": "faiss" if uuid_val in faiss_uuid_to_score else "bm25",
                    "event_kind": row.engram_kind,
                    "entity_type": row.entity_type,
                    "summary_text": row.summary_text,
                    "updates": (row.updates or []) + (row.pending_facts or []),
                })
            if len(primary_events) >= top_k:
                break

        # ── Graph expansion ───────────────────────────────────────────────────
        graph_expanded: List[Dict[str, Any]] = []
        if enable_graph_expansion and graph_hops >= 1 and max_graph_events > 0 and primary_events:
            seed_uuids = [e["event_uuid"] for e in primary_events]
            candidate_weights: Dict[str, float] = {}
            for su in seed_uuids:
                try:
                    for nh_uuid, weight in get_neighbors(user_id, su, db, min_weight=0.1):
                        if nh_uuid in exclude or nh_uuid in seen:
                            continue
                        candidate_weights[nh_uuid] = max(candidate_weights.get(nh_uuid, 0.0), weight)
                except Exception as e:
                    logger.warning("Graph expansion failed for seed %s: %s", su, e)
                    continue
            sorted_candidates = sorted(
                candidate_weights.items(), key=lambda x: x[1], reverse=True
            )[:max_graph_events]
            for nh_uuid, _ in sorted_candidates:
                seen.add(nh_uuid)
                vec = self.faiss_service.get_vector(nh_uuid, index)
                sem = _cosine_sim(query_vec, np.asarray(vec, dtype=np.float32)) if vec is not None else 0.0
                try:
                    row = db.query(Engram).filter(
                        Engram.user_id == user_id,
                        Engram.engram_id == nh_uuid,
                    ).first()
                except Exception as e:
                    logger.warning("Graph expansion DB lookup failed for %s: %s", nh_uuid, e)
                    continue
                if row and row.core_intent and row.engram_kind in _EPISODIC_KINDS:
                    composite, _ = score_engram_with_breakdown(
                        sem, row.relevance_score or 1.0, row.last_updated_at,
                        w_sem, w_rel, w_rec, engram_id=nh_uuid,
                    )
                    graph_expanded.append({
                        "event_uuid": nh_uuid,
                        "core_intent": row.core_intent,
                        "score": composite,
                        "source": "graph",
                        "event_kind": row.engram_kind,
                        "entity_type": row.entity_type,
                        "summary_text": row.summary_text,
                        "updates": (row.updates or []) + (row.pending_facts or []),
                    })

        all_events = sorted(
            primary_events + graph_expanded,
            key=lambda x: x["score"],
            reverse=True,
        )
        logger.debug(
            "C3 result: primary=%d graph=%d total=%d",
            len(primary_events), len(graph_expanded), len(all_events),
        )
        if enable_graph_expansion and primary_events:
            logger.debug(
                "graph_expand: seed_ids=%d → expanded=%d (hops=%d)",
                len(seed_uuids), len(graph_expanded), graph_hops,
            )
        return LongTermResult(
            events=all_events,
            graph_expanded=graph_expanded,
            total_found=len(all_events),
        )

"""
Retrieve service — mode-driven retrieval (faiss | bm25 | hybrid) with hierarchical output.

Each primary episode has entities[] and related_episodes[].
"""
import logging
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

import numpy as np
from sqlalchemy.orm import Session

from hippomem.config import (
    MemoryConfig,
)
from hippomem.decoder.scoring import score_engram_with_breakdown
from hippomem.infra.bm25 import BM25Retriever
from hippomem.infra.graph.queries import get_neighbors
from hippomem.models.engram import Engram, EngramKind
from hippomem.models.engram_link import EngramLink, LinkKind, MentionType
from hippomem.infra.embeddings import EmbeddingService
from hippomem.retrieve.schemas import RetrieveResult, RetrievedEntity, RetrievedEpisode

logger = logging.getLogger(__name__)

_EPISODIC_KINDS = {EngramKind.EPISODE.value, EngramKind.SUMMARY.value}
RetrieveMode = Literal["faiss", "bm25", "hybrid"]


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
) -> Tuple[List[str], Dict[str, float]]:
    """
    Reciprocal Rank Fusion. Returns (merged_uuids, uuid_to_rrf_score).
    """
    scores: Dict[str, float] = {}
    for rank, uuid in enumerate(faiss_uuids):
        scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (k + rank + 1)
    for rank, uuid in enumerate(bm25_uuids):
        scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (k + rank + 1)
    merged = [uuid for uuid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
    return merged, scores


def _row_to_episode(
    row: Engram,
    score: float,
    source: str,
    graph_hop: int,
    cosine_score: Optional[float] = None,
    rrf_score: Optional[float] = None,
    entities: Optional[List[RetrievedEntity]] = None,
    related_episodes: Optional[List[RetrievedEpisode]] = None,
) -> RetrievedEpisode:
    """Build RetrievedEpisode from Engram row."""
    return RetrievedEpisode(
        event_uuid=row.engram_id,
        core_intent=row.core_intent or "",
        score=score,
        source=source,
        event_kind=row.engram_kind or "episode",
        summary_text=row.summary_text,
        updates=(row.updates or []) + (row.pending_facts or []),
        entity_type=row.entity_type,
        cosine_score=cosine_score,
        rrf_score=rrf_score,
        graph_hop=graph_hop,
        entities=entities or [],
        related_episodes=related_episodes or [],
    )


class RetrieveService:
    """Mode-driven retrieval: faiss | bm25 | hybrid, with per-episode entities and related_episodes."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        config: Optional[MemoryConfig] = None,
    ) -> None:
        self.config = config or MemoryConfig()
        self._emb_svc = embedding_service
        from hippomem.infra.vector.faiss_service import FAISSService

        self._faiss = FAISSService(base_dir=self.config.vector_dir)
        self._bm25 = BM25Retriever()

    def retrieve(
        self,
        user_id: str,
        query: str,
        db: Session,
        mode: RetrieveMode = "hybrid",
        top_k: int = 5,
        entity_count: int = 4,
        graph_count: int = 5,
        exclude_uuids: Optional[List[str]] = None,
        rrf_k: Optional[int] = None,
        bm25_index_ttl_seconds: Optional[int] = None,
        w_sem: Optional[float] = None,
        w_rel: Optional[float] = None,
        w_rec: Optional[float] = None,
    ) -> RetrieveResult:
        """
        Retrieve episodes by mode, then expand each with entities and related_episodes.
        """
        exclude = set(exclude_uuids or [])
        rrf_k = rrf_k if rrf_k is not None else self.config.rrf_k
        bm25_ttl = bm25_index_ttl_seconds if bm25_index_ttl_seconds is not None else self.config.bm25_index_ttl_seconds
        w_sem = w_sem if w_sem is not None else self.config.retrieval_semantic_weight
        w_rel = w_rel if w_rel is not None else self.config.retrieval_relevance_weight
        w_rec = w_rec if w_rec is not None else self.config.retrieval_recency_weight

        # Validate
        if top_k < 0:
            raise ValueError("top_k must be >= 0")
        if mode not in ("faiss", "bm25", "hybrid"):
            raise ValueError("mode must be faiss, bm25, or hybrid")

        # Primary retrieval
        primary_candidates: List[Dict[str, Any]] = []
        query_vec: Optional[np.ndarray] = None
        faiss_index = None
        faiss_uuid_to_score: Dict[str, float] = {}
        faiss_uuids: List[str] = []
        bm25_uuids: List[str] = []
        uuid_to_rrf: Dict[str, float] = {}

        if mode in ("faiss", "hybrid"):
            query_vec = np.asarray(
                self._emb_svc.embed(query),
                dtype=np.float32,
            )
            faiss_index = self._faiss.load_index(user_id)
            if faiss_index is None or faiss_index.ntotal == 0:
                if mode == "faiss":
                    return RetrieveResult(episodes=[], total_primary=0)
                # hybrid: continue with BM25 only
            else:
                raw = self._faiss.search(query_vec, top_k * 3, faiss_index, user_id=user_id)
                id_to_uuid = self._faiss.build_id_to_uuid_map(user_id, db)
                for faiss_id, score in raw:
                    uuid_val = id_to_uuid.get(faiss_id)
                    if uuid_val and uuid_val not in faiss_uuid_to_score:
                        faiss_uuids.append(uuid_val)
                        faiss_uuid_to_score[uuid_val] = float(score)

        if mode in ("bm25", "hybrid"):
            bm25_results = self._bm25.retrieve(
                query=query,
                user_id=user_id,
                db=db,
                top_k=top_k * 3,
                ttl_seconds=bm25_ttl,
            )
            bm25_uuids = [r["event_uuid"] for r in bm25_results]

        if mode == "faiss":
            merged_uuids = faiss_uuids
        elif mode == "bm25":
            merged_uuids = bm25_uuids
        else:
            merged_uuids, uuid_to_rrf = _rrf_merge(faiss_uuids, bm25_uuids, k=rrf_k)

        # Build primary episodes with composite scoring
        seen: Set[str] = set()
        for uuid_val in merged_uuids:
            if uuid_val in exclude or uuid_val in seen:
                continue
            seen.add(uuid_val)
            row = db.query(Engram).filter(
                Engram.user_id == user_id,
                Engram.engram_id == uuid_val,
            ).first()
            if not row or not row.core_intent or row.engram_kind not in _EPISODIC_KINDS:
                continue
            cosine = faiss_uuid_to_score.get(uuid_val, 0.0) if query_vec is not None else 0.0
            rrf = uuid_to_rrf.get(uuid_val) if uuid_to_rrf else None
            composite, _ = score_engram_with_breakdown(
                cosine,
                row.relevance_score or 1.0,
                row.last_updated_at,
                w_sem, w_rel, w_rec,
                engram_id=uuid_val,
            )
            in_faiss = uuid_val in faiss_uuid_to_score
            in_bm25 = uuid_val in bm25_uuids
            src = "hybrid" if (in_faiss and in_bm25) else ("faiss" if in_faiss else "bm25")
            primary_candidates.append({
                "row": row,
                "score": composite,
                "source": src,
                "cosine_score": cosine if cosine > 0 else None,
                "rrf_score": rrf,
            })
            if len(primary_candidates) >= top_k:
                break

        # Sort by score descending
        primary_candidates.sort(key=lambda x: x["score"], reverse=True)

        # Build full RetrievedEpisodes with entities and related_episodes
        episodes: List[RetrievedEpisode] = []
        for cand in primary_candidates:
            row = cand["row"]
            entities = self._load_entities_for_episode(
                user_id, row.engram_id, db, entity_count
            )
            related = self._load_related_episodes(
                user_id, row.engram_id, db, graph_count, exclude, seen,
                query_vec, faiss_index, w_sem, w_rel, w_rec,
            )
            ep = _row_to_episode(
                row,
                score=cand["score"],
                source=cand["source"],
                graph_hop=0,
                cosine_score=cand.get("cosine_score"),
                rrf_score=cand.get("rrf_score"),
                entities=entities,
                related_episodes=related,
            )
            episodes.append(ep)

        return RetrieveResult(episodes=episodes, total_primary=len(episodes))

    def _load_entities_for_episode(
        self,
        user_id: str,
        episode_uuid: str,
        db: Session,
        max_entities: int,
    ) -> List[RetrievedEntity]:
        """Load entities linked to episode via MENTION, ranked by mention_type and reinforcement."""
        if max_entities <= 0:
            return []
        try:
            links = (
                db.query(EngramLink)
                .filter(
                    EngramLink.user_id == user_id,
                    EngramLink.link_kind == LinkKind.MENTION.value,
                    EngramLink.source_id == episode_uuid,
                )
                .all()
            )
            if not links:
                return []
            MENTION_PRIORITY = {
                MentionType.PROTAGONIST.value: 0,
                MentionType.SUBJECT.value: 1,
                MentionType.REFERENCED.value: 2,
            }
            entity_best: Dict[str, int] = {}
            for link in links:
                p = MENTION_PRIORITY.get(link.mention_type or "", 99)
                if link.target_id not in entity_best or p < entity_best[link.target_id]:
                    entity_best[link.target_id] = p
            entity_uuids = list(entity_best.keys())
            rows = (
                db.query(Engram)
                .filter(
                    Engram.user_id == user_id,
                    Engram.engram_id.in_(entity_uuids),
                    Engram.engram_kind == EngramKind.ENTITY.value,
                )
                .all()
            )
            uuid_to_row = {r.engram_id: r for r in rows}
            candidates = []
            for eid, priority in entity_best.items():
                r = uuid_to_row.get(eid)
                if not r or not r.core_intent:
                    continue
                candidates.append((r, priority, r.reinforcement_count or 0))
            candidates.sort(key=lambda x: (x[1], -x[2]))
            result = []
            for r, _, _ in candidates[:max_entities]:
                result.append(RetrievedEntity(
                    event_uuid=r.engram_id,
                    core_intent=r.core_intent or "",
                    source="mention",
                    event_kind="entity",
                    entity_type=r.entity_type,
                    summary_text=r.summary_text,
                    updates=(r.updates or []) + (r.pending_facts or []),
                    graph_hop=0,
                ))
            return result
        except Exception as e:
            logger.warning("_load_entities_for_episode failed: %s", e)
            return []

    def _load_related_episodes(
        self,
        user_id: str,
        episode_uuid: str,
        db: Session,
        graph_count: int,
        exclude: Set[str],
        seen: Set[str],
        query_vec: Optional[np.ndarray],
        faiss_index: Optional[Any],
        w_sem: float,
        w_rel: float,
        w_rec: float,
    ) -> List[RetrievedEpisode]:
        """Load graph_count related episodes via graph edges. Full RetrievedEpisode, no recursion."""
        if graph_count <= 0:
            return []
        try:
            neighbors = get_neighbors(user_id, episode_uuid, db, min_weight=0.1)
            neighbors.sort(key=lambda x: x[1], reverse=True)
            result = []
            for nh_uuid, _ in neighbors[:graph_count]:
                if nh_uuid in exclude or nh_uuid in seen:
                    continue
                seen.add(nh_uuid)
                row = db.query(Engram).filter(
                    Engram.user_id == user_id,
                    Engram.engram_id == nh_uuid,
                ).first()
                if not row or not row.core_intent or row.engram_kind not in _EPISODIC_KINDS:
                    continue
                cosine = 0.0
                if query_vec is not None and faiss_index is not None:
                    vec = self._faiss.get_vector(nh_uuid, faiss_index)
                    if vec is not None:
                        cosine = _cosine_sim(query_vec, np.asarray(vec, dtype=np.float32))
                composite, _ = score_engram_with_breakdown(
                    cosine,
                    row.relevance_score or 1.0,
                    row.last_updated_at,
                    w_sem, w_rel, w_rec,
                    engram_id=nh_uuid,
                )
                ep = _row_to_episode(
                    row,
                    score=composite,
                    source="graph",
                    graph_hop=1,
                    cosine_score=cosine if cosine > 0 else None,
                )
                result.append(ep)
            return result
        except Exception as e:
            logger.warning("_load_related_episodes failed: %s", e)
            return []

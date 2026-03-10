"""
Schemas for the retrieve API — hierarchical episode-centric retrieval.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _episode_to_dict(ep: "RetrievedEpisode") -> Dict[str, Any]:
    """Convert RetrievedEpisode to JSON-serializable dict (handles recursion)."""
    return {
        "event_uuid": ep.event_uuid,
        "core_intent": ep.core_intent,
        "score": ep.score,
        "source": ep.source,
        "event_kind": ep.event_kind,
        "summary_text": ep.summary_text,
        "updates": ep.updates,
        "entity_type": ep.entity_type,
        "cosine_score": ep.cosine_score,
        "rrf_score": ep.rrf_score,
        "graph_hop": ep.graph_hop,
        "entities": [asdict(e) for e in ep.entities],
        "related_episodes": [_episode_to_dict(r) for r in ep.related_episodes],
    }


def retrieve_result_to_dict(result: "RetrieveResult") -> Dict[str, Any]:
    """Convert RetrieveResult to JSON-serializable dict."""
    return {
        "episodes": [_episode_to_dict(ep) for ep in result.episodes],
        "total_primary": result.total_primary,
    }


@dataclass
class RetrievedEntity:
    """Entity engram linked to an episode via MENTION."""

    event_uuid: str
    core_intent: str
    score: Optional[float] = None
    source: str = "mention"
    event_kind: str = "entity"
    entity_type: Optional[str] = None
    summary_text: Optional[str] = None
    updates: List[Any] = field(default_factory=list)
    cosine_score: Optional[float] = None
    rrf_score: Optional[float] = None
    graph_hop: Optional[int] = None


@dataclass
class RetrievedEpisode:
    """Episode or summary engram with nested entities and related episodes."""

    event_uuid: str
    core_intent: str
    score: float
    source: str  # "faiss" | "bm25" | "graph"
    event_kind: str  # "episode" | "summary"
    summary_text: Optional[str] = None
    updates: List[Any] = field(default_factory=list)
    entity_type: Optional[str] = None
    cosine_score: Optional[float] = None
    rrf_score: Optional[float] = None
    graph_hop: Optional[int] = None  # 0 = primary, 1+ = related
    entities: List[RetrievedEntity] = field(default_factory=list)
    related_episodes: List["RetrievedEpisode"] = field(default_factory=list)


@dataclass
class RetrieveResult:
    """Result of retrieve() — hierarchical episodes with entities and related episodes."""

    episodes: List[RetrievedEpisode]
    total_primary: int

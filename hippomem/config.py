"""
hippomem configuration.

MemoryConfig holds all tunable memory parameters with sensible defaults.
Pass an instance to MemoryService to override any value.

Module-level weight constants are the single source of truth for algorithm
defaults shared across submodules.  Import from here to stay in sync.
"""
from dataclasses import dataclass

# Retrieval scoring weight defaults — shared with retriever/scoring.py
DEFAULT_RETRIEVAL_SEMANTIC_WEIGHT: float = 0.5
DEFAULT_RETRIEVAL_RELEVANCE_WEIGHT: float = 0.3
DEFAULT_RETRIEVAL_RECENCY_WEIGHT: float = 0.2

# Edge weight defaults — shared with graph/edges.py and vector/edges.py
DEFAULT_EDGE_SIMILARITY_ALPHA: float = 0.1
DEFAULT_EDGE_TRIADIC_BONUS: float = 0.02
DEFAULT_EDGE_RETRIEVAL_BONUS: float = 0.15
DEFAULT_EDGE_TEMPORAL_BONUS: float = 0.15
DEFAULT_EDGE_TOP_K: int = 20
DEFAULT_EDGE_MIN_SIMILARITY: float = 0.75


@dataclass
class MemoryConfig:
    # ── Working memory capacity ───────────────────────────────────────────────
    max_active_events: int = 5
    """Max events in working memory per user. Maps to human working memory limit."""

    max_dormant_events: int = 5
    """Recently demoted events kept for C3 retrieval."""

    ephemeral_trace_capacity: int = 8
    """Max weak traces per user/session before FIFO eviction."""

    # ── Decay ─────────────────────────────────────────────────────────────────
    decay_rate_per_hour: float = 0.98
    """Relevance multiplier per hour (~2%/hr, ~40%/day if unused)."""

    # ── Retrieval cascade thresholds ──────────────────────────────────────────
    continuation_threshold: float = 0.7
    """C1 confidence threshold to skip C3 escalation."""

    local_scan_threshold: float = 0.6
    """C2 score threshold for high-confidence result (skips C3)."""

    conversation_window_turns: int = 2
    """Recent conversation turns passed to C1/C2/C3."""

    # ── Retrieval scoring weights ─────────────────────────────────────────────
    retrieval_semantic_weight: float = DEFAULT_RETRIEVAL_SEMANTIC_WEIGHT
    retrieval_relevance_weight: float = DEFAULT_RETRIEVAL_RELEVANCE_WEIGHT
    retrieval_recency_weight: float = DEFAULT_RETRIEVAL_RECENCY_WEIGHT

    # ── Edge weights ──────────────────────────────────────────────────────────
    edge_similarity_alpha: float = DEFAULT_EDGE_SIMILARITY_ALPHA
    """Base weight added when two events are semantically similar (FAISS)."""

    edge_triadic_bonus: float = DEFAULT_EDGE_TRIADIC_BONUS
    """Bonus applied to close a triangle between already-connected neighbors."""

    edge_retrieval_bonus: float = DEFAULT_EDGE_RETRIEVAL_BONUS
    """Bonus when two events are surfaced together in the same synthesis."""

    edge_temporal_bonus: float = DEFAULT_EDGE_TEMPORAL_BONUS
    """Bonus linking predecessor events to a newly branched event."""

    edge_top_k: int = DEFAULT_EDGE_TOP_K
    """Number of FAISS neighbors considered for real-time edge processing."""

    edge_min_similarity: float = DEFAULT_EDGE_MIN_SIMILARITY
    """Minimum FAISS similarity score for a neighbor to receive a similarity edge."""

    # ── Graph expansion (C3) ──────────────────────────────────────────────────
    enable_graph_expansion: bool = True
    graph_hops: int = 1
    max_graph_events: int = 5

    # ── BM25 / hybrid retrieval (C3) ─────────────────────────────────────────
    enable_bm25: bool = True
    """Run BM25 keyword search alongside FAISS in C3; results merged via RRF."""

    bm25_index_ttl_seconds: int = 300
    """Seconds before the per-user BM25 index is rebuilt (default: 5 min)."""

    rrf_k: int = 60
    """Reciprocal Rank Fusion constant k. Higher k smooths rank differences."""

    # ── Memory updater window sizes ───────────────────────────────────────────
    updater_detect_drift_turns: int = 5
    updater_should_create_turns: int = 5
    updater_extract_update_turns: int = 2
    updater_generate_event_turns: int = 3
    updater_history_turns: int = 20

    # ── LLM / embedding ───────────────────────────────────────────────────────
    llm_model: str = "x-ai/grok-4.1-fast"
    embedding_model: str = "text-embedding-3-small"
    llm_max_retries: int = 3
    llm_retry_delay: float = 1.0
    llm_timeout: float = 60.0

    # ── Storage ───────────────────────────────────────────────────────────────
    db_url: str = "sqlite:///.hippomem/hippomem.db"
    vector_dir: str = ".hippomem/vectors"

    # ── Background consolidation (v0.2) ───────────────────────────────────────
    enable_background_consolidation: bool = False
    """Run periodic decay + staleness demotion in an asyncio background task."""

    consolidation_interval_hours: float = 1.0
    """How often (in hours) the background consolidation cycle runs."""

    # ── Self memory (v1.6) ────────────────────────────────────────────────────
    enable_self_memory: bool = True
    """Extract and track durable user identity signals (goals, preferences, personality)."""

    # ── Episode consolidation ─────────────────────────────────────────────────
    enable_episode_consolidation: bool = True
    """Compress accumulated episode update statements during consolidate() runs."""

    # ── Entity extraction (v1.5) ──────────────────────────────────────────────
    enable_entity_extraction: bool = True
    """Extract and track named entities (persons, orgs, places, projects, pets) after each encode."""

    updater_entity_extract_turns: int = 4
    """Recent turns passed as context to the entity extraction LLM call."""


    # ── Turn linking ──────────────────────────────────────────────────────────
    turn_link_max_age_seconds: int = 600
    """Max age (seconds) for a decode row to be linked to an encode via DB fallback (Tier 3)."""

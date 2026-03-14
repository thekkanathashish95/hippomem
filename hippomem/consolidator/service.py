"""
Memory Consolidation Service — decay and Engram persistence.
Single authority for relevance score decay on active events.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy.orm import Session

from hippomem.models.working_state import WorkingState
from hippomem.models.engram import Engram, EngramKind
from hippomem.schemas.working_state import WorkingStateData

if TYPE_CHECKING:
    from hippomem.infra.embeddings import EmbeddingService
    from hippomem.consolidator.llm_ops import ConsolidationLLMOps

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationConfig:
    max_active_events: int = 5
    max_dormant_events: int = 5
    relevance_decay_rate: float = 0.98  # per hour; ~2% loss/hour, ~40% loss/day


class ConsolidationService:
    """
    Single authority for applying decay to active events in Engram.
    Demotion is handled entirely by the encoder (FIFO on capacity).
    """

    def __init__(self, config: Optional[ConsolidationConfig] = None) -> None:
        self.config = config or ConsolidationConfig()

    def apply_decay(
        self,
        user_id: str,
        session_id: Optional[str],
        db: Session,
        working_state: Optional[WorkingStateData] = None,
    ) -> None:
        """Apply decay to active events. When working_state is None, loads from db."""
        if working_state is None:
            working_state = self._load_working_state(user_id, session_id, db)
        if not working_state or not working_state.active_event_uuids:
            return
        self.apply_decay_uuids(user_id, session_id, working_state.active_event_uuids, db)

    def apply_decay_uuids(
        self,
        user_id: str,
        session_id: Optional[str],
        active_uuids: List[str],
        db: Session,
    ) -> None:
        """Apply per-hour decay to active events in Engram."""
        if not active_uuids:
            return
        logger.debug("decay_pass: user=%s engrams_processed=%d", user_id, len(active_uuids))
        now = datetime.now(timezone.utc)
        rows = db.query(Engram).filter(
            Engram.user_id == user_id,
            Engram.engram_id.in_(active_uuids),
        ).all()
        for row in rows:
            last_decay = row.last_decay_applied_at
            if not last_decay:
                row.last_decay_applied_at = now
                continue
            try:
                if last_decay.tzinfo is None:
                    last_decay = last_decay.replace(tzinfo=timezone.utc)
            except (TypeError, AttributeError) as e:
                logger.warning("Invalid last_decay_applied_at for event %s: %s", row.engram_id, e)
                row.last_decay_applied_at = now
                continue
            delta = now - last_decay
            hours_since = delta.total_seconds() / 3600.0
            if hours_since <= 0:
                continue
            score_before = row.relevance_score or 1.0
            decay_factor = self.config.relevance_decay_rate ** hours_since
            score_after = max(0.0, min(1.0, score_before * decay_factor))
            row.relevance_score = score_after
            row.last_decay_applied_at = now
            logger.debug(
                "decay: engram=%s score_before=%.3f score_after=%.3f",
                row.engram_id, score_before, score_after,
            )

    def _load_working_state(
        self,
        user_id: str,
        session_id: Optional[str],
        db: Session,
    ) -> Optional[WorkingStateData]:
        return WorkingState.load(db, user_id, session_id)

    def _persist_working_state(
        self,
        user_id: str,
        session_id: Optional[str],
        working_state: WorkingStateData,
        db: Session,
    ) -> None:
        WorkingState.persist(db, user_id, session_id, working_state)


def prune_stale_traits(
    user_id: str,
    db: Session,
    stale_days: int = 30,
    min_evidence_to_keep: int = 2,
    min_confidence_to_keep: float = 0.7,
) -> int:
    """
    Deactivate traits that are unlikely to still be relevant.

    A trait is deactivated if ALL of:
    - evidence_count < min_evidence_to_keep  (seen only once — never reinforced)
    - last_observed_at older than stale_days
    - confidence_score < min_confidence_to_keep

    The AND logic is intentionally conservative: a high-confidence single-shot
    preference ("always use bullet points") survives because confidence >= 0.7.
    A frequently-reinforced trait (evidence_count >= 2) also survives regardless
    of recency. Only low-evidence, low-confidence, long-unobserved traits are pruned.

    Returns count deactivated.
    """
    from hippomem.models.self_trait import SelfTrait

    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    try:
        stale = (
            db.query(SelfTrait)
            .filter(
                SelfTrait.user_id == user_id,
                SelfTrait.is_active,
                SelfTrait.evidence_count < min_evidence_to_keep,
                SelfTrait.last_observed_at < cutoff,
                SelfTrait.confidence_score < min_confidence_to_keep,
            )
            .all()
        )
        for trait in stale:
            trait.is_active = False
        if stale:
            db.commit()
            logger.info("prune_stale_traits: user=%s deactivated=%d", user_id, len(stale))
        return len(stale)
    except Exception as e:
        logger.error("prune_stale_traits failed for user %s: %s", user_id, e)
        return 0


def consolidate_self_memory(
    user_id: str,
    db: Session,
    llm_ops: "ConsolidationLLMOps",
    min_confidence: float = 0.5,
) -> bool:
    """
    Generate or update the persona Engram for a user from their active SelfTraits.

    Returns True if the persona Engram was updated, False if traits unchanged.
    """
    from collections import defaultdict

    from hippomem.models.engram import Engram, EngramKind
    from hippomem.memory.self.service import get_active_traits, compute_traits_hash

    traits = [
        t for t in get_active_traits(user_id, db)
        if t.confidence_score >= min_confidence
    ]
    if not traits:
        return False

    current_hash = compute_traits_hash(traits)

    persona = (
        db.query(Engram)
        .filter(
            Engram.user_id == user_id,
            Engram.engram_kind == EngramKind.PERSONA.value,
        )
        .first()
    )

    if persona and persona.content_hash == current_hash:
        return False  # traits unchanged since last consolidation — skip LLM call

    # Group traits by category for the LLM call
    by_category: Dict[str, List[str]] = defaultdict(list)
    for t in traits:
        by_category[t.category].append(f"{t.key}: {t.value}")

    identity_summary = llm_ops.generate_identity_summary(by_category)

    now = datetime.now(timezone.utc)
    if persona is None:
        import uuid as uuid_module

        engram_id = str(uuid_module.uuid4())
        persona = Engram(
            user_id=user_id,
            engram_id=engram_id,
            engram_kind=EngramKind.PERSONA.value,
            core_intent="self_profile",
            summary_text=identity_summary,
            content_hash=current_hash,
            relevance_score=1.0,
            last_decay_applied_at=now,
        )
        db.add(persona)
    else:
        persona.summary_text = identity_summary
        persona.content_hash = current_hash
        persona.updated_at = now

    db.commit()
    logger.info("Self memory consolidated for user %s", user_id)
    return True


def consolidate_user(
    user_id: str,
    db: Session,
    enable_episode_consolidation: bool = True,
    enable_entity_extraction: bool = False,
    consolidation_llm_ops: Optional["ConsolidationLLMOps"] = None,
    embedding_service: Optional["EmbeddingService"] = None,
    vector_dir: str = ".hippomem/vectors",
    enable_self_memory: bool = False,
    self_trait_min_confidence: float = 0.5,
) -> None:
    """
    Run all periodic maintenance for a single user.
    Decay and demotion are handled by the encoder on each turn.
    Called by MemoryService.consolidate() and BackgroundConsolidationTask.
    """
    # 1. Episode fact consolidation
    if enable_episode_consolidation and consolidation_llm_ops and embedding_service:
        try:
            n = consolidate_episode_facts(
                user_id=user_id,
                db=db,
                llm_ops=consolidation_llm_ops,
                embedding_service=embedding_service,
                vector_dir=vector_dir,
            )
            logger.debug("episode_consolidation: user=%s episodes_consolidated=%d", user_id, n)
        except Exception as e:
            logger.error("Episode consolidation failed for user=%s: %s", user_id, e)

    # 2. Entity enrichment
    if enable_entity_extraction and consolidation_llm_ops and embedding_service:
        try:
            n = enrich_entity_profiles(
                user_id=user_id,
                db=db,
                llm_ops=consolidation_llm_ops,
                embedding_service=embedding_service,
                vector_dir=vector_dir,
            )
            logger.debug("entity_enrichment: user=%s entities_enriched=%d", user_id, n)
        except Exception as e:
            logger.error("Entity enrichment failed for user=%s: %s", user_id, e)

    # 3. Prune stale traits
    if enable_self_memory:
        try:
            n = prune_stale_traits(user_id, db)
            logger.debug("trait_pruning: user=%s deactivated=%d", user_id, n)
        except Exception as e:
            logger.error("Trait pruning failed for user=%s: %s", user_id, e)

    # 4. Self memory consolidation
    if enable_self_memory and consolidation_llm_ops:
        try:
            persona_updated = consolidate_self_memory(
                user_id,
                db,
                consolidation_llm_ops,
                min_confidence=self_trait_min_confidence,
            )
            logger.debug("self_memory: user=%s persona_updated=%s", user_id, persona_updated)
        except Exception as e:
            logger.error("Self consolidation failed for user=%s: %s", user_id, e)


def enrich_entity_profiles(
    user_id: str,
    db: Session,
    llm_ops: "ConsolidationLLMOps",
    embedding_service: "EmbeddingService",
    vector_dir: str,
    entity_decay_rate: float = 0.999,
) -> int:
    """
    For each entity engram with pending facts:
    1. Apply entity-specific decay
    2. Merge pending facts into consolidated baseline via LLM
    3. Re-embed with full content (name + summary + merged facts)
    4. Clear pending_facts and needs_consolidation flag

    Returns count of entities enriched.
    """
    from hippomem.infra.vector.faiss_service import FAISSService
    from hippomem.infra.vector.embedding import compute_content_hash, add_to_faiss_realtime

    entity_rows = db.query(Engram).filter(
        Engram.user_id == user_id,
        Engram.engram_kind == EngramKind.ENTITY.value,
        Engram.needs_consolidation.is_(True),
    ).all()

    if not entity_rows:
        return 0

    faiss_svc = FAISSService(base_dir=vector_dir)
    index = faiss_svc.get_or_create_index(user_id)
    now = datetime.now(timezone.utc)
    enriched = 0

    for row in entity_rows:
        # 1. Entity decay
        last_decay = row.last_decay_applied_at
        if last_decay:
            if last_decay.tzinfo is None:
                last_decay = last_decay.replace(tzinfo=timezone.utc)
            hours = (now - last_decay).total_seconds() / 3600.0
            if hours > 0:
                score = row.relevance_score or 1.0
                row.relevance_score = max(
                    0.0, min(1.0, score * (entity_decay_rate ** hours))
                )
        row.last_decay_applied_at = now

        try:
            # 2. Merge pending facts into consolidated baseline
            result = llm_ops.update_entity_profile(
                canonical_name=row.core_intent or "",
                entity_type=row.entity_type or "entity",
                consolidated_facts=list(row.updates or []),
                pending_facts=list(row.pending_facts or []),
                existing_summary=row.summary_text,
            )
            row.updates = result["merged_facts"]
            row.summary_text = result["summary_text"]
            row.pending_facts = []
            row.needs_consolidation = False

            # 3. Re-embed with full content (name + summary + merged facts)
            summary = row.summary_text or ""
            facts = row.updates or []
            embed_parts = [f"{row.core_intent} ({row.entity_type or 'entity'})"]
            if summary:
                embed_parts.append(summary)
            if facts:
                embed_parts.append("\n".join(facts))
            embed_text = "\n".join(embed_parts)

            vector = embedding_service.embed(embed_text)
            content_hash = compute_content_hash(row.core_intent or "", row.updates)
            add_to_faiss_realtime(
                user_id, row.engram_id, vector, content_hash, faiss_svc, index, db
            )
            enriched += 1
        except Exception as e:
            logger.error("Entity enrichment failed for %s: %s", row.core_intent, e)

    if enriched > 0:
        faiss_svc.save_index(user_id, index)
    db.commit()
    logger.info("Enriched %d entity profiles for user %s", enriched, user_id)
    return enriched


def consolidate_episode_facts(
    user_id: str,
    db: Session,
    llm_ops: "ConsolidationLLMOps",
    embedding_service: "EmbeddingService",
    vector_dir: str,
) -> int:
    """
    For each episode engram with pending facts:
    1. Merge pending update statements into consolidated baseline via LLM
    2. Re-embed with merged updates
    3. Clear pending_facts and needs_consolidation flag

    Returns count of episodes consolidated.
    """
    from hippomem.infra.vector.faiss_service import FAISSService
    from hippomem.infra.vector.embedding import compute_content_hash, add_to_faiss_realtime, embed_engram

    episode_rows = db.query(Engram).filter(
        Engram.user_id == user_id,
        Engram.engram_kind == EngramKind.EPISODE.value,
        Engram.needs_consolidation.is_(True),
    ).all()

    if not episode_rows:
        return 0

    faiss_svc = FAISSService(base_dir=vector_dir)
    index = faiss_svc.get_or_create_index(user_id)
    consolidated = 0

    for row in episode_rows:
        try:
            result = llm_ops.consolidate_episode_updates(
                core_intent=row.core_intent or "",
                consolidated_updates=list(row.updates or []),
                pending_updates=list(row.pending_facts or []),
            )
            row.updates = result["merged_updates"]
            row.pending_facts = []
            row.needs_consolidation = False
            row.updated_at = datetime.now(timezone.utc)

            embed_result = embed_engram(
                row.engram_id, row.core_intent or "", row.updates, embedding_service
            )
            if embed_result:
                vector, content_hash = embed_result
                add_to_faiss_realtime(
                    user_id, row.engram_id, vector, content_hash, faiss_svc, index, db
                )
            consolidated += 1
        except Exception as e:
            logger.error("Episode consolidation failed for %s: %s", row.engram_id, e)

    if consolidated > 0:
        faiss_svc.save_index(user_id, index)
    db.commit()
    logger.info("Consolidated %d episode engrams for user %s", consolidated, user_id)
    return consolidated

"""
Memory Encoder - Post-inference memory updates.
Updates working state after each conversation turn.
Engram is source of truth; WorkingState stores only UUIDs.

Entity extraction orchestration is absorbed here (was entity/extractor.py).
"""
import logging
import uuid as uuid_module
from typing import Callable, Dict, Any, List, Optional, Set, Tuple, TYPE_CHECKING
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from hippomem.models.working_state import WorkingState
from hippomem.models.engram import Engram, EngramKind
from hippomem.models.engram_link import EngramLink, LinkKind
from hippomem.schemas.working_state import WorkingStateData
from hippomem.config import MemoryConfig
from hippomem.infra.embeddings import EmbeddingService
from hippomem.memory.episodic.llm_ops import EpisodicLLMOps
from hippomem.memory.entity.llm_ops import EntityLLMOps
from hippomem.memory.entity.schemas import ExtractedEntity

if TYPE_CHECKING:
    from hippomem.memory.self.extractor import SelfExtractor
from hippomem.infra.vector.embedding import compute_content_hash, embed_engram, add_to_faiss_realtime
from hippomem.infra.vector.edges import process_links_realtime
from hippomem.infra.vector.faiss_service import FAISSService
from hippomem.consolidator.service import ConsolidationService, ConsolidationConfig
from hippomem.infra.graph.edges import strengthen_temporal_links, strengthen_retrieval_links
from hippomem.memory.traces import service as traces_svc
from hippomem.decoder.context_builder import format_recent_turns

logger = logging.getLogger(__name__)


def _all_facts(row) -> List[str]:
    """Return the full fact list for an engram: consolidated updates + pending facts."""
    return (row.updates or []) + (row.pending_facts or [])


def _truncate_facts(facts: List[str], max_chars: int = 3000, max_fact_chars: int = 300) -> str:
    """
    Join facts into a preview string.
    Each individual fact is truncated to max_fact_chars (with '...').
    Stops adding facts once the total would exceed max_chars.
    """
    if not facts:
        return "no prior facts"
    parts: List[str] = []
    total = 0
    for fact in facts:
        truncated = fact if len(fact) <= max_fact_chars else fact[:max_fact_chars - 3] + "..."
        if total and total + len(truncated) + 2 > max_chars:
            break
        parts.append(truncated)
        total += len(truncated) + 2  # +2 for "; " separator
    return "; ".join(parts)


def _build_entity_embed_text(canonical_name: str, entity_type: str, facts: List[str]) -> str:
    """Construct embedding text for entity node (no summary_text yet — consolidation adds that)."""
    parts = [f"{canonical_name} ({entity_type})"]
    if facts:
        parts.append("\n".join(facts))
    return "\n".join(parts)


class MemoryEncoder:
    """
    Post-inference component that updates working state.
    This is the ONLY component that mutates memory.

    Entity extraction orchestration is absorbed here when entity_llm_ops is provided.
    """

    def __init__(
        self,
        llm_ops: EpisodicLLMOps,
        embedding_service: EmbeddingService,
        consolidation_service: Optional[ConsolidationService] = None,
        config: Optional[MemoryConfig] = None,
        entity_llm_ops: Optional[EntityLLMOps] = None,
        self_extractor: Optional["SelfExtractor"] = None,
    ) -> None:
        self.episodic_llm = llm_ops
        self.embedding_service = embedding_service
        self.config = config or MemoryConfig()
        self.entity_llm_ops = entity_llm_ops
        self.self_extractor = self_extractor
        self.consolidation = consolidation_service or ConsolidationService(
            config=ConsolidationConfig(
                max_active_events=self.config.max_active_events,
                max_dormant_events=self.config.max_dormant_events,
                relevance_decay_rate=self.config.decay_rate_per_hour,
            )
        )

    def update(
        self,
        user_id: str,
        session_id: Optional[str],
        conversation_history: List[Tuple[str, str]],
        db: Session,
        used_engram_ids: Optional[List[str]] = None,
        reasoning: Optional[str] = None,
        synthesized_context: Optional[str] = None,
        used_entity_ids: Optional[List[str]] = None,
        on_step: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Update working state based on conversation turn.

        Args:
            user_id: User identifier
            session_id: Optional session identifier
            conversation_history: Last N (user, agent) turn pairs; last element is current turn.
                Caller builds this; memory encoder never fetches conversation from DB.
            db: Database session
            used_engram_ids: Engram IDs used in synthesis (from ContextSynthesizer)
            reasoning: Why those events were chosen
            synthesized_context: What was given to the agent
            used_entity_ids: Entity engram IDs used in synthesis (from ContextSynthesizer)

        Returns:
            Dict with working_state and event_id (engram_id for message linking)
        """
        def step(label: str) -> None:
            if on_step:
                on_step(label)

        if not conversation_history:
            working_state = self._load_or_create_working_state(user_id, session_id, db)
            return {"working_state": working_state.model_dump(), "event_id": None, "action": "skip"}

        user_message, agent_response = conversation_history[-1]
        used_engram_ids = used_engram_ids or []
        working_state = self._load_or_create_working_state(user_id, session_id, db)

        event_uuid_result: Optional[str] = None
        action: str = "skip"

        step("Analyzing conversation")

        if used_engram_ids:
            logger.debug("path=A reason=used_engram_ids")
            # Path A: Update used events (no create, no LLM decision)
            event_uuid_result, action = self._update_used_events(
                user_id, working_state,
                used_engram_ids, user_message, agent_response,
                conversation_history, db,
                reasoning=reasoning,
                synthesized_context=synthesized_context,
            )
        else:
            logger.debug("path=B reason=cold_start")
            # Path B: Create new event or append to ETS
            event_uuid_result, action = self._create_or_ets(
                user_id, session_id, working_state,
                user_message, agent_response, conversation_history, db
            )

        # Apply decay to active events
        self._apply_decay_to_active(user_id, session_id, working_state, db)

        # Demote when capacity exceeded
        demoted = self._handle_demotion(working_state)
        max_active = self.consolidation.config.max_active_events
        logger.debug(
            "working_state: active=%d/%d demoted=%d",
            len(working_state.active_event_uuids), max_active, len(demoted),
        )

        # Persist working state
        working_state.last_updated = datetime.now(timezone.utc).isoformat()
        self._persist_working_state(user_id, session_id, working_state, db)

        # Reinforce entities that were selected into synthesis context this turn
        if used_entity_ids and self.entity_llm_ops:
            try:
                self._reinforce_used_entities(user_id, used_entity_ids, db)
            except Exception as e:
                logger.error("Entity reinforcement failed for user %s: %s", user_id, e)

        # Entity extraction — always runs if entity_llm_ops is set, regardless of episodic path.
        # episode_uuid may be None (ETS/skip turns): entities are still created/updated,
        # but no MENTION link is created for turns that produced no episode.
        if not self.entity_llm_ops:
            logger.info("entity_extract: skipped — entity_llm_ops is None (enable_entity_extraction=%s)",
                        self.config.enable_entity_extraction)
        else:
            step("Extracting entities")
            try:
                self._extract_and_link_entities(
                    user_id=user_id,
                    episode_uuid=event_uuid_result,
                    user_message=user_message,
                    agent_response=agent_response,
                    conversation_history=conversation_history,
                    db=db,
                    known_entity_uuids=set(used_entity_ids or []),
                )
            except Exception as e:
                logger.error("Entity extraction failed for user %s: %s", user_id, e)

        # Self extraction — runs synchronously in the same executor call as encode
        # Runs regardless of whether event_uuid_result is set (unlike entity extraction)
        if self.self_extractor:
            step("Updating self model")
            try:
                self.self_extractor.extract_and_accumulate(
                    user_id=user_id,
                    user_message=user_message,
                    conversation_history=conversation_history,
                    db=db,
                )
            except Exception as e:
                logger.error("Self extraction failed for user %s: %s", user_id, e)

        return {"working_state": working_state.model_dump(), "event_id": event_uuid_result, "action": action}

    def _update_used_events(
        self,
        user_id: str,
        working_state: WorkingStateData,
        used_engram_ids: List[str],
        user_message: str,
        agent_response: str,
        conversation_history: List[Tuple[str, str]],
        db: Session,
        reasoning: Optional[str] = None,
        synthesized_context: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        """Update retrieval state and event content for used events. Returns (event_uuid, action)."""
        decision = "update_existing"
        reason: Optional[str] = None
        active_row = db.query(Engram).filter(
            Engram.user_id == user_id,
            Engram.engram_id == used_engram_ids[0],
        ).first()
        active_core_intent = (active_row.core_intent or "").strip() if active_row else ""
        active_event_updates = list(active_row.updates or []) if active_row else []
        if active_core_intent:
            recent_turns = format_recent_turns(
                conversation_history, self.config.updater_detect_drift_turns
            )
            decision, reason = self.episodic_llm.detect_drift(
                active_core_intent, user_message, agent_response,
                recent_turns=recent_turns,
                active_event_updates=active_event_updates,
            )

        if decision == "create_new_branch":
            logger.debug("path_A: drift=create_new_branch engram=%s", used_engram_ids[0])
            event_uuid, _ = self._create_new_event(
                user_id, working_state,
                user_message, agent_response, conversation_history, db,
                drift_from_intent=active_core_intent,
            )
            strengthen_temporal_links(user_id, [used_engram_ids[0]], event_uuid, db)
            return event_uuid, "create_new_branch"

        # update_existing: promote used events, update their content
        logger.debug("path_A: drift=update_existing engram=%s", used_engram_ids[0])
        self._update_retrieval_state(user_id, working_state, used_engram_ids, db)
        db.commit()

        recent_turns_extract = format_recent_turns(
            conversation_history, self.config.updater_extract_update_turns
        )
        self._update_event_content(
            user_id, used_engram_ids, user_message, agent_response, db,
            reasoning=reasoning,
            synthesized_context=synthesized_context,
            recent_turns=recent_turns_extract,
        )

        if len(used_engram_ids) > 1:
            strengthen_retrieval_links(user_id, used_engram_ids, db)

        return used_engram_ids[0], "update_existing"

    def _update_retrieval_state(
        self,
        user_id: str,
        working_state: WorkingStateData,
        used_engram_ids: List[str],
        db: Session,
    ) -> None:
        """Update last_touched in Engram, handle promotion."""
        now = datetime.now(timezone.utc)
        active = working_state.active_event_uuids
        dormant = working_state.recent_dormant_uuids

        for event_uuid in used_engram_ids:
            row = db.query(Engram).filter(
                Engram.user_id == user_id,
                Engram.engram_id == event_uuid,
            ).first()
            if row:
                row.last_updated_at = now
                row.reinforcement_count = (row.reinforcement_count or 0) + 1

            if event_uuid in dormant:
                dormant.remove(event_uuid)
                active.insert(0, event_uuid)
            elif event_uuid not in active:
                active.insert(0, event_uuid)
            else:
                if active[0] != event_uuid:
                    active.remove(event_uuid)
                    active.insert(0, event_uuid)

        db.flush()

    def _reinforce_used_entities(
        self,
        user_id: str,
        used_entity_ids: List[str],
        db: Session,
    ) -> None:
        """Bump reinforcement_count and last_updated_at for entity engrams used in synthesis."""
        now = datetime.now(timezone.utc)
        rows = (
            db.query(Engram)
            .filter(
                Engram.user_id == user_id,
                Engram.engram_id.in_(used_entity_ids),
                Engram.engram_kind == EngramKind.ENTITY.value,
            )
            .all()
        )
        for row in rows:
            row.reinforcement_count = (row.reinforcement_count or 0) + 1
            row.last_updated_at = now
        db.flush()
        logger.debug("entity_reinforce: user=%s count=%d", user_id, len(rows))

    def _update_event_content(
        self,
        user_id: str,
        used_engram_ids: List[str],
        user_message: str,
        agent_response: str,
        db: Session,
        reasoning: Optional[str] = None,
        synthesized_context: Optional[str] = None,
        recent_turns: Optional[str] = None,
    ) -> None:
        """Update core_intent and updates in Engram via LLM; re-embed and update edges when content changes."""
        faiss_svc = FAISSService(base_dir=self.config.vector_dir)
        event_tuples: List[Tuple[str, Any, Dict[str, Any]]] = []
        for event_uuid in used_engram_ids:
            row = db.query(Engram).filter(
                Engram.user_id == user_id,
                Engram.engram_id == event_uuid,
            ).first()
            if not row or not row.core_intent:
                continue
            event = {
                "event_uuid": event_uuid,
                "core_intent": row.core_intent or "",
                "updates": row.updates or [],
            }
            event_tuples.append((event_uuid, row, event))

        if not event_tuples:
            return

        events = [e for (_, _, e) in event_tuples]
        updated_list = self.episodic_llm.extract_event_update(
            events, user_message, agent_response,
            reasoning=reasoning,
            synthesized_context=synthesized_context,
            recent_turns=recent_turns,
        )

        index = faiss_svc.load_index(user_id) or faiss_svc.get_or_create_index(user_id)
        faiss_dirty = False

        for (event_uuid, row, _), updated in zip(event_tuples, updated_list):
            new_pending = list(row.pending_facts or [])
            new_core_intent = row.core_intent or ""
            fact_added = False
            if updated.get("add_update") and updated.get("update"):
                new_pending.append(updated["update"])
                fact_added = True
            if updated.get("refined_core_intent"):
                new_core_intent = updated["refined_core_intent"]
            all_facts = list(row.updates or []) + new_pending
            new_content_hash = compute_content_hash(new_core_intent, all_facts)
            content_hash_changed = new_content_hash != row.content_hash
            logger.debug(
                "path_A update: content_hash_changed=%s → %s",
                content_hash_changed, "re-embed" if content_hash_changed else "skip",
            )
            if content_hash_changed:
                row.core_intent = new_core_intent
                row.pending_facts = new_pending
                if fact_added:
                    row.needs_consolidation = True
                row.content_hash = new_content_hash
                row.updated_at = datetime.now(timezone.utc)
                if index:
                    result = embed_engram(
                        event_uuid, new_core_intent, all_facts,
                        self.embedding_service,
                    )
                    if result:
                        try:
                            vector, content_hash = result
                            add_to_faiss_realtime(user_id, event_uuid, vector, content_hash, faiss_svc, index, db)
                            processed_pairs: Set[Tuple[str, str]] = set()
                            process_links_realtime(user_id, event_uuid, vector, db, faiss_svc, index, processed_pairs)
                            faiss_dirty = True
                        except Exception as e:
                            logger.error("FAISS write failed for event %s: %s", event_uuid, e)
            else:
                row.updated_at = datetime.now(timezone.utc)

        if faiss_dirty:
            faiss_svc.save_index(user_id, index)

    def _create_or_ets(
        self,
        user_id: str,
        session_id: Optional[str],
        working_state: WorkingStateData,
        user_message: str,
        agent_response: str,
        conversation_history: List[Tuple[str, str]],
        db: Session,
    ) -> Tuple[Optional[str], str]:
        """Create new event or append to ETS. Returns (event_uuid, action)."""
        ets_traces = traces_svc.get_traces(user_id, session_id, db)
        recent_turns_create = format_recent_turns(
            conversation_history, self.config.updater_should_create_turns
        )
        should_create, reason = self.episodic_llm.should_create_new_event(
            user_message, agent_response,
            ets_traces=ets_traces,
            recent_turns=recent_turns_create,
        )
        logger.debug("path_B: should_create=%s", should_create)

        if should_create:
            event_uuid, _ = self._create_new_event(
                user_id, working_state,
                user_message, agent_response, conversation_history, db
            )
            return event_uuid, "create_new"

        # ETS path
        store, trace_summary = self.episodic_llm.maybe_append_to_ets(
            user_message, agent_response,
            existing_traces=ets_traces,
            recent_turns=recent_turns_create,
        )
        appended_to_ets = bool(store and trace_summary)
        logger.debug("path_B skip: appended_to_ets=%s", appended_to_ets)
        if appended_to_ets:
            traces_svc.append_trace(user_id, session_id, trace_summary, db,
                                 max_size=self.config.ephemeral_trace_capacity)
        return None, "append_trace" if appended_to_ets else "skip"

    def _create_new_event(
        self,
        user_id: str,
        working_state: WorkingStateData,
        user_message: str,
        agent_response: str,
        conversation_history: List[Tuple[str, str]],
        db: Session,
        drift_from_intent: Optional[str] = None,
    ) -> Tuple[Optional[str], List[str]]:
        """Create event, persist to Engram, add to active_event_uuids."""
        active = working_state.active_event_uuids

        recent_turns_gen = format_recent_turns(
            conversation_history, self.config.updater_generate_event_turns
        )
        event_uuid = str(uuid_module.uuid4())
        new_event_dict = self.episodic_llm.generate_new_event(
            user_message, agent_response, recent_turns=recent_turns_gen,
            drift_from_intent=drift_from_intent,
        )

        now = datetime.now(timezone.utc)
        core_intent = new_event_dict.get("core_intent", "")
        updates = new_event_dict.get("updates", []) or []
        content_hash = compute_content_hash(core_intent, updates)

        store = Engram(
            user_id=user_id,
            engram_id=event_uuid,
            content_hash=content_hash,
            core_intent=core_intent,
            updates=updates,
            reinforcement_count=0,
            relevance_score=1.0,
            last_decay_applied_at=now,
            last_updated_at=now,
        )
        db.add(store)
        db.flush()

        faiss_svc = FAISSService(base_dir=self.config.vector_dir)
        index = faiss_svc.get_or_create_index(user_id)
        result = embed_engram(event_uuid, core_intent, updates, self.embedding_service)
        if result:
            try:
                vector, content_hash = result
                add_to_faiss_realtime(user_id, event_uuid, vector, content_hash, faiss_svc, index, db)
                processed_pairs: Set[Tuple[str, str]] = set()
                process_links_realtime(user_id, event_uuid, vector, db, faiss_svc, index, processed_pairs)
                faiss_svc.save_index(user_id, index)
            except Exception as e:
                logger.error("FAISS write failed for new event %s: %s", event_uuid, e)

        # Temporal edge: new event succeeds most recent active event
        if active:
            strengthen_temporal_links(user_id, [active[0]], event_uuid, db)

        working_state.active_event_uuids = [event_uuid] + working_state.active_event_uuids

        logger.info("Created new event %s for user %s", event_uuid, user_id)
        return event_uuid, []

    def _load_events_from_store(
        self,
        user_id: str,
        event_uuids: List[str],
        db: Session,
    ) -> List[Dict[str, Any]]:
        if not event_uuids:
            return []
        rows = db.query(Engram).filter(
            Engram.user_id == user_id,
            Engram.engram_id.in_(event_uuids),
        ).all()
        uuid_to_row = {r.engram_id: r for r in rows}
        events = []
        for i, u in enumerate(event_uuids):
            row = uuid_to_row.get(u)
            if row:
                events.append({
                    "event_id": f"E{i + 1}",
                    "event_uuid": u,
                    "core_intent": row.core_intent or "",
                    "updates": row.updates or [],
                    "relevance_score": row.relevance_score or 1.0,
                    "last_touched": row.last_updated_at.isoformat() if row.last_updated_at else None,
                    "reinforcement_count": row.reinforcement_count or 0,
                })
        return sorted(
            events,
            key=lambda e: (e.get("last_touched") or "", e.get("event_id", "")),
            reverse=True,
        )

    def _apply_decay_to_active(
        self,
        user_id: str,
        session_id: Optional[str],
        working_state: WorkingStateData,
        db: Session,
    ) -> None:
        active = working_state.active_event_uuids
        if not active:
            return
        self.consolidation.apply_decay_uuids(user_id, session_id, active, db)

    def _handle_demotion(self, working_state: WorkingStateData) -> List[str]:
        """FIFO demotion when over capacity. Returns list of demoted UUIDs."""
        max_active = self.consolidation.config.max_active_events
        max_dormant = self.consolidation.config.max_dormant_events
        active = working_state.active_event_uuids
        dormant = working_state.recent_dormant_uuids
        demoted = []
        while len(active) > max_active:
            u = active.pop()
            demoted.append(u)
            dormant.insert(0, u)
            if len(dormant) > max_dormant:
                dormant.pop()
        return demoted

    def _load_hint_entity_details(
        self,
        entity_uuids: Set[str],
        user_id: str,
        db: Session,
    ) -> List[Dict[str, Any]]:
        """
        Batch-load name, entity_type, and top facts for a set of entity UUIDs.
        Returns only entities that exist and have a non-null core_intent.
        Order matches iteration order of entity_uuids.
        """
        rows = (
            db.query(Engram)
            .filter(
                Engram.user_id == user_id,
                Engram.engram_id.in_(entity_uuids),
                Engram.engram_kind == EngramKind.ENTITY.value,
                Engram.core_intent.isnot(None),
            )
            .all()
        )
        return [
            {
                "uuid": row.engram_id,
                "name": row.core_intent,
                "entity_type": row.entity_type or "other",
                "facts": _all_facts(row),
            }
            for row in rows
        ]

    def _extract_and_link_entities(
        self,
        user_id: str,
        episode_uuid: Optional[str],
        user_message: str,
        agent_response: str,
        conversation_history: List[Tuple[str, str]],
        db: Session,
        known_entity_uuids: Optional[Set[str]] = None,
    ) -> None:
        """
        Extract entities from current turn, find-or-create entity nodes, optionally link to episode.

        episode_uuid may be None when the turn went to ETS or was skipped by the episodic path.
        In that case, entities are still created/updated but no MENTION link is written
        (there is no episode to link to).

        known_entity_uuids: entity UUIDs resolved by the decoder this turn — used to build hint
        anchors (H1, H2, ...) that are injected into the extraction prompt so the LLM can directly
        identify known entities without requiring post-hoc name matching or disambiguation.
        """
        recent_turns = format_recent_turns(conversation_history, num_turns=self.config.updater_entity_extract_turns)

        # Build hint map: H-prefix aliases → UUID, and format a hint block for the prompt
        hint_map: Dict[str, str] = {}
        hint_block = ""
        if known_entity_uuids:
            hint_entities = self._load_hint_entity_details(known_entity_uuids, user_id, db)
            if hint_entities:
                lines = []
                for i, ent in enumerate(hint_entities, 1):
                    alias = f"H{i}"
                    hint_map[alias] = ent["uuid"]
                    facts_preview = _truncate_facts(ent["facts"], max_chars=3000, max_fact_chars=300)
                    lines.append(f"{alias}: {ent['name']} ({ent['entity_type']}) — {facts_preview}")
                hint_block = "**Known entities (likely referenced in this turn):**\n" + "\n".join(lines) + "\n\n"

        result = self.entity_llm_ops.extract_entities(
            user_message, agent_response, recent_turns, hint_block=hint_block
        )
        significant = [e for e in result.entities if e.significant]
        logger.info("entity_extract: user=%s episode=%s found=%d significant=%d hints=%d",
                    user_id, episode_uuid or "none", len(result.entities), len(significant), len(hint_map))

        for extracted in result.entities:
            if not extracted.significant:
                continue
            try:
                # Hint anchor: LLM confirmed this is a known entity — skip name scan + disambiguation
                if extracted.hint_id and extracted.hint_id in hint_map:
                    resolved_uuid = hint_map[extracted.hint_id]
                    faiss_svc = FAISSService(base_dir=self.config.vector_dir)
                    index = faiss_svc.get_or_create_index(user_id)
                    entity_uuid = self._append_facts_to_entity(
                        resolved_uuid, extracted, user_id, db, faiss_svc, index
                    )
                    logger.debug("entity='%s' match=hint_anchor uuid=%s", extracted.canonical_name, resolved_uuid)
                else:
                    entity_uuid = self._find_or_create_entity(
                        extracted, user_id, db,
                        user_message=user_message,
                        agent_response=agent_response,
                        recent_turns=recent_turns,
                    )
                if entity_uuid and episode_uuid:
                    self._link_entity_to_episode(
                        user_id, episode_uuid, entity_uuid, extracted.mention_type, db
                    )
                db.commit()  # release lock before next entity (avoids holding across embedding API calls)
            except Exception as e:
                db.rollback()
                logger.error(
                    "Entity processing failed for '%s': %s", extracted.canonical_name, e
                )

    def _find_entity_candidates_by_name(
        self,
        canonical_name: str,
        entity_type: str,
        user_id: str,
        db: Session,
    ) -> List[Tuple[str, "Engram"]]:
        """
        Return existing entity rows that name-match canonical_name.

        Match tiers (in priority order):
          - exact:     case-insensitive equality
          - substring: one name is a substring of the other
          - token:     share ≥1 meaningful token (len > 2)

        Filters to matching entity_type only to reduce false positives.
        Returns list of (match_tier, row).
        """
        rows = (
            db.query(Engram)
            .filter(
                Engram.user_id == user_id,
                Engram.engram_kind == EngramKind.ENTITY.value,
                Engram.entity_type == entity_type,
            )
            .all()
        )

        name_lower = canonical_name.lower().strip()
        name_tokens = {t for t in name_lower.split() if len(t) > 2}

        candidates: List[Tuple[str, Engram]] = []
        for row in rows:
            existing_lower = (row.core_intent or "").lower().strip()
            if not existing_lower:
                continue

            if name_lower == existing_lower:
                candidates.append(("exact", row))
            elif name_lower in existing_lower or existing_lower in name_lower:
                candidates.append(("substring", row))
            elif name_tokens:
                existing_tokens = {t for t in existing_lower.split() if len(t) > 2}
                if name_tokens & existing_tokens:
                    candidates.append(("token", row))

        return candidates

    def _find_or_create_entity(
        self,
        extracted: ExtractedEntity,
        user_id: str,
        db: Session,
        user_message: str = "",
        agent_response: str = "",
        recent_turns: str = "",
    ) -> Optional[str]:
        """
        Find existing entity node by name or create a new one.

        Only called for entities with no hint_id (new entities not in decoder hints).

        Lookup strategy:
          1. Name-based DB scan (exact → substring → token overlap), same entity_type only
          2. Single exact match → auto update (no LLM needed)
          3. Any ambiguity (multiple matches, or non-exact) → LLM disambiguate
          4. No match / LLM returns null → create new
        """
        faiss_svc = FAISSService(base_dir=self.config.vector_dir)

        candidates = self._find_entity_candidates_by_name(
            extracted.canonical_name, extracted.entity_type, user_id, db
        )

        if not candidates:
            logger.debug("entity='%s' match=none → create", extracted.canonical_name)
            return self._create_entity_node(extracted, user_id, db, faiss_svc)

        # Single exact match → auto update, no disambiguation needed
        exact = [(tier, row) for tier, row in candidates if tier == "exact"]
        if len(exact) == 1:
            matched_row = exact[0][1]
            logger.debug("entity='%s' match=exact uuid=%s", extracted.canonical_name, matched_row.engram_id)
            index = faiss_svc.get_or_create_index(user_id)
            return self._append_facts_to_entity(
                matched_row.engram_id, extracted, user_id, db, faiss_svc, index
            )

        # Multiple exact matches OR non-exact matches → LLM disambiguate
        candidates_for_llm = [
            {
                "name": row.core_intent,
                "facts": _all_facts(row),
                "entity_uuid": row.engram_id,
            }
            for _, row in candidates
        ]
        mention_context_parts = []
        if recent_turns:
            mention_context_parts.append(f"Recent turns:\n{recent_turns}")
        if user_message:
            mention_context_parts.append(f"User: {user_message}")
        if agent_response:
            mention_context_parts.append(f"Agent: {agent_response}")
        mention_context = "\n\n".join(mention_context_parts) if mention_context_parts else extracted.canonical_name
        result = self.entity_llm_ops.disambiguate_entity(
            new_name=extracted.canonical_name,
            entity_type=extracted.entity_type,
            mention_context=mention_context,
            candidates=candidates_for_llm,
        )
        if result.match:
            try:
                idx = int(result.match.split("_")[1]) - 1
                _, matched_row = candidates[idx]
                logger.debug("entity='%s' match=disambiguate uuid=%s", extracted.canonical_name, matched_row.engram_id)
                index = faiss_svc.get_or_create_index(user_id)
                return self._append_facts_to_entity(
                    matched_row.engram_id, extracted, user_id, db, faiss_svc, index
                )
            except (IndexError, ValueError):
                pass

        logger.debug("entity='%s' match=none (llm returned null) → create", extracted.canonical_name)
        return self._create_entity_node(extracted, user_id, db, faiss_svc)

    def _append_facts_to_entity(
        self,
        entity_uuid: str,
        extracted: ExtractedEntity,
        user_id: str,
        db: Session,
        faiss_svc: FAISSService,
        index,
    ) -> str:
        """Append new facts to existing entity node and re-embed."""
        row = (
            db.query(Engram)
            .filter(
                Engram.user_id == user_id,
                Engram.engram_id == entity_uuid,
            )
            .first()
        )
        if not row:
            return entity_uuid

        existing_consolidated = list(row.updates or [])
        existing_pending = list(row.pending_facts or [])
        all_known = existing_consolidated + existing_pending
        new_facts = [f for f in extracted.facts if f not in all_known]
        row.reinforcement_count = (row.reinforcement_count or 0) + 1
        re_embedded = False
        if new_facts:
            new_pending = existing_pending + new_facts
            row.pending_facts = new_pending
            row.needs_consolidation = True
            row.updated_at = datetime.now(timezone.utc)

            all_facts = existing_consolidated + new_pending
            embed_text = _build_entity_embed_text(
                row.core_intent, row.entity_type or extracted.entity_type, all_facts
            )
            try:
                vector = self.embedding_service.embed(embed_text)
                content_hash = compute_content_hash(row.core_intent, all_facts)
                add_to_faiss_realtime(
                    user_id, entity_uuid, vector, content_hash, faiss_svc, index, db
                )
                faiss_svc.save_index(user_id, index)
                re_embedded = True
            except Exception as e:
                logger.error("Re-embed failed for entity %s: %s", entity_uuid, e)

        logger.debug("entity=%s facts_added=%d re_embedded=%s", entity_uuid, len(new_facts), re_embedded)
        db.flush()
        return entity_uuid

    def _create_entity_node(
        self,
        extracted: ExtractedEntity,
        user_id: str,
        db: Session,
        faiss_svc: FAISSService,
    ) -> Optional[str]:
        """Create new entity Engram row and add to FAISS."""
        entity_uuid = str(uuid_module.uuid4())
        now = datetime.now(timezone.utc)
        content_hash = compute_content_hash(extracted.canonical_name, extracted.facts)

        node = Engram(
            user_id=user_id,
            engram_id=entity_uuid,
            engram_kind=EngramKind.ENTITY.value,
            entity_type=extracted.entity_type,
            core_intent=extracted.canonical_name,
            updates=[],
            pending_facts=list(extracted.facts),
            needs_consolidation=True,
            summary_text=None,
            content_hash=content_hash,
            relevance_score=1.0,
            reinforcement_count=1,
            last_decay_applied_at=now,
            last_updated_at=now,
        )
        db.add(node)
        db.flush()
        logger.debug("entity=%s match=create sim=0.000", entity_uuid)

        embed_text = _build_entity_embed_text(
            extracted.canonical_name, extracted.entity_type, extracted.facts
        )
        try:
            index = faiss_svc.get_or_create_index(user_id)
            vector = self.embedding_service.embed(embed_text)
            add_to_faiss_realtime(
                user_id, entity_uuid, vector, content_hash, faiss_svc, index, db
            )
            faiss_svc.save_index(user_id, index)
        except Exception as e:
            logger.error("FAISS write failed for new entity %s: %s", entity_uuid, e)

        return entity_uuid

    def _link_entity_to_episode(
        self,
        user_id: str,
        episode_uuid: str,
        entity_uuid: str,
        mention_type: str,
        db: Session,
    ) -> None:
        """Create EngramLink with link_kind=MENTION between episode and entity."""
        existing_link = (
            db.query(EngramLink)
            .filter(
                EngramLink.user_id == user_id,
                EngramLink.source_id == episode_uuid,
                EngramLink.target_id == entity_uuid,
                EngramLink.link_kind == LinkKind.MENTION.value,
            )
            .first()
        )
        if not existing_link:
            link = EngramLink(
                user_id=user_id,
                source_id=episode_uuid,
                target_id=entity_uuid,
                link_kind=LinkKind.MENTION.value,
                mention_type=mention_type,
            )
            db.add(link)

        db.flush()

    def _load_or_create_working_state(
        self,
        user_id: str,
        session_id: Optional[str],
        db: Session,
    ) -> WorkingStateData:
        return WorkingState.load_or_create(db, user_id, session_id)

    def _persist_working_state(
        self,
        user_id: str,
        session_id: Optional[str],
        working_state: WorkingStateData,
        db: Session,
    ) -> None:
        WorkingState.persist(db, user_id, session_id, working_state)

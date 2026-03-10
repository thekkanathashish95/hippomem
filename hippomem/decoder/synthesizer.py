"""
Context Synthesizer - Pre-inference memory synthesis with retrieval cascade.
C1: Continuation Check → C2: Local Scan → C3: Long-Term Retrieval (if needed).
Returns used_engram_ids for the memory encoder.
"""
import logging
from typing import Callable, Dict, Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from hippomem.models.working_state import WorkingState
from hippomem.schemas.working_state import WorkingStateData
from hippomem.models.engram import Engram, EngramKind
from hippomem.models.engram_link import EngramLink, LinkKind, MentionType
from hippomem.infra.llm import LLMService
from hippomem.infra.embeddings import EmbeddingService
from hippomem.config import MemoryConfig
from hippomem.decoder.schemas import ContinuationResult
from hippomem.decoder.llm_ops import DecoderLLMOps
from hippomem.decoder.context_builder import get_conversation_window
from hippomem.decoder.local_scan import LocalScanRanker, LocalScanResult
from hippomem.decoder.long_term import LongTermRetriever, LongTermResult
from hippomem.infra.vector.faiss_service import FAISSService

logger = logging.getLogger(__name__)


class ContextSynthesizer:
    """Pre-inference component with retrieval cascade: C1 → C2 → C3."""

    def __init__(
        self,
        llm_service: LLMService,
        embedding_service: EmbeddingService,
        config: Optional[MemoryConfig] = None,
    ) -> None:
        self.config = config or MemoryConfig()
        self.decoder_llm_ops = DecoderLLMOps(llm_service)
        faiss_svc = FAISSService(base_dir=self.config.vector_dir)
        self.local_scan = LocalScanRanker(
            embedding_service=embedding_service,
            faiss_service=faiss_svc,
        )
        self.long_term_retriever = LongTermRetriever(
            embedding_service=embedding_service,
            faiss_service=faiss_svc,
        )

    def synthesize(
        self,
        user_id: str,
        session_id: Optional[str],
        user_message: str,
        conversation_history: List[Tuple[str, str]],
        db: Session,
        on_step: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Synthesize memory context via retrieval cascade.

        Args:
            user_id: User identifier
            session_id: Optional session identifier
            user_message: Current user message
            conversation_history: All (user, assistant) turn pairs; last element is current turn
            db: Database session

        Returns:
            {"synthesized_context": str, "used_engram_ids": List[str], "reasoning": str}
        """
        def step(label: str) -> None:
            if on_step:
                on_step(label)

        conversation_window = get_conversation_window(
            conversation_history, num_turns=self.config.conversation_window_turns
        )

        active_events, dormant_objectives = self._load_event_context(user_id, session_id, db)

        current_active_event = active_events[0] if active_events else None

        # C1: Continuation Check (skip if no active events)
        c1_result = None
        if active_events:
            step("Checking continuation")
            try:
                c1_result = self.decoder_llm_ops.check_continuation(
                    current_message=user_message,
                    conversation_window=conversation_window,
                    current_event=current_active_event,
                )
                threshold = self.config.continuation_threshold
                outcome = "skipping C3" if (
                    c1_result.decision == "CONTINUE" and c1_result.confidence >= threshold
                ) else "continuing"
                logger.debug(
                    "C1: decision=%s conf=%.3f → %s",
                    c1_result.decision, c1_result.confidence, outcome,
                )
            except Exception as e:
                logger.warning("C1 check failed: %s", e)

        # C2: Local Scan (skip when C1 says CONTINUE with high confidence — saves query embedding)
        threshold = self.config.continuation_threshold
        skip_c2 = (
            c1_result is not None
            and c1_result.decision == "CONTINUE"
            and c1_result.confidence >= threshold
        )
        if skip_c2:
            c2_result = LocalScanResult(events=[], high_confidence=True)
            logger.debug("C2: skipped (C1 CONTINUE high confidence)")
        else:
            step("Scanning memories")
            c2_result = self.local_scan.scan_and_rank(
                query=user_message,
                conversation_window=conversation_window,
                active_events=active_events,
                dormant_events=dormant_objectives,
                user_id=user_id,
                db=db,
                threshold=self.config.local_scan_threshold,
                w_sem=self.config.retrieval_semantic_weight,
                w_rel=self.config.retrieval_relevance_weight,
                w_rec=self.config.retrieval_recency_weight,
            )
            c2_outcome = "skipping C3" if c2_result.high_confidence else "continuing"
            logger.debug("C2: high_confidence=%s → %s", c2_result.high_confidence, c2_outcome)

        # C3: Long-term retrieval (if needed)
        threshold = self.config.continuation_threshold
        should_escalate = (
            c1_result is None
            or c1_result.decision in ("SHIFT", "UNCERTAIN")
            or c1_result.confidence < threshold
        ) and not c2_result.high_confidence

        c3_result = None
        if should_escalate:
            step("Retrieving long-term memories")
            exclude_uuids = [
                uid for uid in (
                    e.get("event_uuid") or e.get("event_id")
                    for e in active_events + dormant_objectives
                )
                if uid
            ]
            try:
                c3_result = self.long_term_retriever.retrieve(
                    query=user_message,
                    conversation_window=conversation_window,
                    exclude_uuids=exclude_uuids,
                    user_id=user_id,
                    db=db,
                    enable_graph_expansion=self.config.enable_graph_expansion,
                    graph_hops=self.config.graph_hops,
                    max_graph_events=self.config.max_graph_events,
                    enable_bm25=self.config.enable_bm25,
                    bm25_index_ttl_seconds=self.config.bm25_index_ttl_seconds,
                    rrf_k=self.config.rrf_k,
                    w_sem=self.config.retrieval_semantic_weight,
                    w_rel=self.config.retrieval_relevance_weight,
                    w_rec=self.config.retrieval_recency_weight,
                )
            except Exception as e:
                logger.warning("C3 retrieval failed for user %s: %s", user_id, e)

        events_for_synthesis, id_to_uuid, cascade = self._collect_events_for_synthesis(
            c1_result=c1_result,
            current_active=current_active_event,
            c2_events=c2_result.events,
            c3_result=c3_result,
            active_events=active_events,
            dormant_objectives=dormant_objectives,
            c2_high_confidence=c2_result.high_confidence,
            should_escalate=should_escalate,
        )

        if not events_for_synthesis:
            return {
                "synthesized_context": "",
                "used_engram_ids": [],
                "used_entity_ids": [],
                "reasoning": "",
                "cascade": "C2",
            }

        self_profile, self_src = self._load_self_profile(user_id, db)
        logger.debug("self_profile: source=%s", self_src)

        event_uuids_for_entities = [
            e.get("event_uuid") for e in events_for_synthesis if e.get("event_uuid")
        ]
        linked_entities = self._load_linked_entities(event_uuids_for_entities, user_id, db)
        if linked_entities:
            logger.debug("linked_entities: count=%d", len(linked_entities))

        # Same order as in llm_ops when building N1, N2, ... so N-prefix in events_used resolve correctly
        entity_id_to_uuid = {f"N{i + 1}": e["event_uuid"] for i, e in enumerate(linked_entities) if e.get("event_uuid")}

        step("Synthesizing context")
        result = self._synthesize_with_llm(
            events_for_synthesis=events_for_synthesis,
            id_to_uuid=id_to_uuid,
            user_message=user_message,
            self_profile=self_profile,
            linked_entities=linked_entities,
            entity_id_to_uuid=entity_id_to_uuid,
        )
        result["cascade"] = cascade
        used = result.get("used_engram_ids", [])
        uuid_to_id = {v: k for k, v in id_to_uuid.items()}
        display_ids = [uuid_to_id.get(u, u) for u in used if u]
        logger.debug(
            "synthesis: events_used=%d display_ids=%s",
            len(used), display_ids,
        )
        return result

    def _collect_events_for_synthesis(
        self,
        c1_result: Optional[ContinuationResult],
        current_active: Optional[Dict[str, Any]],
        c2_events: List[Dict[str, Any]],
        c3_result: Optional[LongTermResult],
        active_events: List[Dict[str, Any]],
        dormant_objectives: List[Dict[str, Any]],
        c2_high_confidence: bool = False,
        should_escalate: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str], str]:
        """Build event list and id_to_uuid mapping based on cascade decisions. Returns (events, id_to_uuid, cascade)."""
        threshold = self.config.continuation_threshold

        # CONTINUE + high confidence → use current event only (C1)
        if (
            c1_result is not None
            and c1_result.decision == "CONTINUE"
            and c1_result.confidence >= threshold
        ):
            events = [current_active] if current_active else []
            id_to_uuid = self._build_id_to_uuid_mapping(active_events, dormant_objectives)
            return events, id_to_uuid, "C1"

        # C3 triggered
        if should_escalate and c3_result and c3_result.events:
            cascade = "C3"
        else:
            cascade = "C2"

        # Otherwise: C2 events + C3 events (if any)
        id_to_uuid = self._build_id_to_uuid_mapping(active_events, dormant_objectives)
        uuid_to_id = {v: k for k, v in id_to_uuid.items()}
        events = []
        for e in c2_events:
            uuid_val = e.get("event_uuid") or e.get("event_id")
            if not uuid_val:
                continue
            display_id = uuid_to_id.get(uuid_val)
            if not display_id:
                # C2 only scores events from active/dormant scope — this should never happen
                logger.warning("C2 returned event outside active/dormant scope: %s", uuid_val)
                continue
            events.append({**e, "event_id": display_id})

        if c3_result and c3_result.events:
            for i, e in enumerate(c3_result.events):
                eid = f"L{i + 1}"
                events.append({**e, "event_id": eid})
                id_to_uuid[eid] = e.get("event_uuid", "")

        return events, id_to_uuid, cascade

    def _load_event_context(
        self,
        user_id: str,
        session_id: Optional[str],
        db: Session,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Load active + dormant from working state (single DB round-trip)."""
        working_state = self._load_working_state(user_id, session_id, db)
        if not working_state:
            return [], []
        active_events = self._load_events_from_event_store(
            user_id, working_state.active_event_uuids or [], db, id_prefix="E"
        )
        dormant_uuids = (working_state.recent_dormant_uuids or [])[:self.config.max_dormant_events]
        dormant_objectives = self._load_events_from_event_store(
            user_id, dormant_uuids, db, id_prefix="D"
        )
        return active_events, dormant_objectives

    def _load_events_from_event_store(
        self,
        user_id: str,
        event_uuids: List[str],
        db: Session,
        id_prefix: str = "E",
    ) -> List[Dict[str, Any]]:
        if not event_uuids:
            return []
        try:
            rows = (
                db.query(Engram)
                .filter(
                    Engram.user_id == user_id,
                    Engram.engram_id.in_(event_uuids),
                    Engram.core_intent.isnot(None),
                    Engram.engram_kind != EngramKind.ENTITY.value,
                )
                .all()
            )
        except Exception as e:
            logger.warning("_load_events_from_event_store failed for user %s: %s", user_id, e)
            return []
        uuid_to_row = {r.engram_id: r for r in rows}
        events = []
        for i, uuid in enumerate(event_uuids):
            row = uuid_to_row.get(uuid)
            if row:
                events.append({
                    "event_id": f"{id_prefix}{i + 1}",
                    "event_uuid": uuid,
                    "core_intent": row.core_intent or "",
                    "updates": row.updates or [],
                    "event_kind": row.engram_kind or "episode",
                    "entity_type": row.entity_type,
                    "summary_text": row.summary_text,
                })
        return events

    def _build_id_to_uuid_mapping(
        self,
        active_events: List[Dict[str, Any]],
        dormant_objectives: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for i, event in enumerate(active_events):
            display_id = event.get("event_id") or f"E{i + 1}"
            uuid_val = event.get("event_uuid")
            if uuid_val:
                mapping[display_id] = uuid_val
        for i, obj in enumerate(dormant_objectives):
            display_id = obj.get("event_id") or f"D{i + 1}"
            uuid_val = obj.get("event_uuid") or obj.get("event_id")
            if uuid_val:
                mapping[display_id] = uuid_val
        return mapping

    def _load_linked_entities(
        self,
        event_uuids: List[str],
        user_id: str,
        db: Session,
        max_entities: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Load entity engrams linked to shortlisted events via MENTION links.
        Ranked by mention_type (protagonist > subject > referenced), then reinforcement_count desc.
        N-prefix IDs are assigned by the caller (llm_ops); UUIDs are NOT added to id_to_uuid.
        Gated by config.enable_entity_extraction; returns [] on any failure.
        """
        if not event_uuids or not self.config.enable_entity_extraction:
            return []
        try:
            links = (
                db.query(EngramLink)
                .filter(
                    EngramLink.user_id == user_id,
                    EngramLink.link_kind == LinkKind.MENTION.value,
                    EngramLink.source_id.in_(event_uuids),
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
            # Keep best (lowest priority) mention_type per entity
            entity_best: Dict[str, int] = {}
            for link in links:
                priority = MENTION_PRIORITY.get(link.mention_type or "", 99)
                if link.target_id not in entity_best or priority < entity_best[link.target_id]:
                    entity_best[link.target_id] = priority

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
            for entity_uuid, priority in entity_best.items():
                row = uuid_to_row.get(entity_uuid)
                if not row or not row.core_intent:
                    continue
                candidates.append({
                    "event_uuid": entity_uuid,
                    "core_intent": row.core_intent,
                    "entity_type": row.entity_type,
                    "summary_text": row.summary_text,
                    "updates": row.updates or [],
                    "event_kind": "entity",
                    "_mention_priority": priority,
                    "_reinforcement_count": row.reinforcement_count or 0,
                })

            candidates.sort(key=lambda x: (x["_mention_priority"], -x["_reinforcement_count"]))
            for c in candidates:
                c.pop("_mention_priority")
                c.pop("_reinforcement_count")
            return candidates[:max_entities]

        except Exception as e:
            logger.warning("_load_linked_entities failed for user %s: %s", user_id, e)
            return []

    def _load_self_profile(self, user_id: str, db: Session) -> Tuple[Optional[str], str]:
        """
        Returns (identity_context, source) for the synthesis prompt.
        source: "persona" | "traits" | "none"

        Priority:
        1. Persona Engram summary_text (exists after consolidate() has been called)
        2. Direct trait injection (fallback — always available if self memory is enabled)
        3. None (self memory disabled or no traits yet)
        """
        if not self.config.enable_self_memory:
            return None, "none"

        try:
            persona = (
                db.query(Engram)
                .filter(
                    Engram.user_id == user_id,
                    Engram.engram_kind == EngramKind.PERSONA.value,
                )
                .first()
            )
            if persona and persona.summary_text:
                return persona.summary_text, "persona"

            # Fallback: direct trait injection
            from hippomem.memory.self.service import get_active_traits, format_traits_for_injection

            traits = get_active_traits(user_id, db)
            if traits:
                return format_traits_for_injection(traits), "traits"
        except Exception as e:
            logger.warning("_load_self_profile failed for user %s: %s", user_id, e)

        return None, "none"

    def _load_working_state(
        self,
        user_id: str,
        session_id: Optional[str],
        db: Session,
    ) -> Optional[WorkingStateData]:
        try:
            ws = WorkingState.for_scope(db, user_id, session_id).first()
            return ws.state_data if ws else None
        except Exception as e:
            logger.warning("_load_working_state failed for user %s: %s", user_id, e)
            return None

    def _synthesize_with_llm(
        self,
        events_for_synthesis: List[Dict[str, Any]],
        id_to_uuid: Dict[str, str],
        user_message: str,
        self_profile: Optional[str] = None,
        linked_entities: Optional[List[Dict[str, Any]]] = None,
        entity_id_to_uuid: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Delegate to DecoderLLMOps.synthesize with fallback on failure."""
        try:
            return self.decoder_llm_ops.synthesize(
                events_for_synthesis, id_to_uuid, user_message,
                self_profile=self_profile,
                linked_entities=linked_entities,
                entity_id_to_uuid=entity_id_to_uuid,
            )
        except Exception as e:
            logger.warning("Structured synthesis failed (%s), using fallback", e)
            return self._fallback_synthesis(events_for_synthesis, id_to_uuid)

    def _fallback_synthesis(
        self,
        events: List[Dict[str, Any]],
        id_to_uuid: Dict[str, str],
    ) -> Dict[str, Any]:
        if not events:
            return {"synthesized_context": "", "used_engram_ids": [], "used_entity_ids": [], "reasoning": ""}
        intents = [e.get("core_intent", "") for e in events]
        used_uuids = [
            id_to_uuid[e["event_id"]]
            for e in events
            if e.get("event_id") and e["event_id"] in id_to_uuid
        ]
        return {
            "synthesized_context": "Current context: " + ", ".join(intents),
            "used_engram_ids": used_uuids,
            "used_entity_ids": [],
            "reasoning": "Fallback: LLM synthesis failed.",
        }

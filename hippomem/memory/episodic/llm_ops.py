"""
Episodic LLM Operations - Drift detection, event updates, new event creation.
Prompts loaded from hippomem/prompts/encoder.yaml.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional

from hippomem.infra.llm import LLMService
from hippomem.prompts import get_encoder_prompts

from hippomem.memory.episodic.schemas import (
    ExtractEventUpdateResponse,
    DetectDriftResponse,
    ShouldCreateNewEventResponse,
    GenerateNewEventResponse,
    MaybeAppendToEtsResponse,
)

logger = logging.getLogger(__name__)


def _build_user_message(operation: str, **kwargs: Any) -> str:
    """Build user message from template and kwargs."""
    prompts = get_encoder_prompts(operation)
    template = prompts.get("user_template", "")
    return template.format(**kwargs)


class EpisodicLLMOps:
    """Uses LLM to perform episodic memory operations."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm = llm_service

    def extract_event_update(
        self,
        events: List[Dict[str, Any]],
        user_message: str,
        agent_response: str,
        reasoning: Optional[str] = None,
        synthesized_context: Optional[str] = None,
        recent_turns: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Use LLM to update engram fields intelligently. Accepts one or more events.
        Returns list of {add_update, update, refined_core_intent}—one per event, in order.
        """
        if not events:
            return []

        blocks = []
        for i, ev in enumerate(events, 1):
            core_intent = ev.get("core_intent", "")
            updates = ev.get("updates", [])
            updates_str = "\n".join(f"  - {u}" for u in updates) if updates else "  (none)"
            blocks.append(f"Memory {i}:\n  Core intent: {core_intent}\n  Updates:\n{updates_str}")
        memories_block = "\n\n".join(blocks)

        if synthesized_context or reasoning:
            memory_section = "Context given to the agent for this turn:\n"
            if synthesized_context:
                memory_section += f"{synthesized_context}\n"
            if reasoning:
                memory_section += f"Why these were chosen: {reasoning}"
        else:
            memory_section = "(none)"

        recent_turns = (recent_turns or "").strip() or "(No previous turns)"
        prompts = get_encoder_prompts("extract_event_update")
        user_content = _build_user_message(
            "extract_event_update",
            memories_block=memories_block,
            user_message=user_message,
            agent_response=agent_response,
            memory_section=memory_section,
            recent_turns=recent_turns,
        )
        input_messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=input_messages,
                response_model=ExtractEventUpdateResponse,
                temperature=0.3,
                max_tokens=4000,
                op="extract_event_update",
            )
            updates_list = [u.model_dump() for u in result.updates]
            fallback = {"add_update": False, "update": None, "refined_core_intent": None}
            while len(updates_list) < len(events):
                updates_list.append(fallback)
            return updates_list[: len(events)]
        except Exception as e:
            logger.error("Error extracting event update: %s", e)
            return [{"add_update": False, "update": None, "refined_core_intent": None}] * len(events)

    def detect_drift(
        self,
        active_core_intent: str,
        user_message: str,
        agent_response: str,
        recent_turns: Optional[str] = None,
        active_event_updates: Optional[List[str]] = None,
    ) -> Tuple[str, Optional[str]]:
        """
        Determine if current turn drifted from active memory's semantic center.
        Returns (decision, reason) — decision is "update_existing" or "create_new_branch".
        """
        recent_turns = (recent_turns or "").strip() or "(No previous turns)"
        updates = active_event_updates or []
        active_event_updates_block = (
            "\n".join(f"  - {u}" for u in updates) if updates else "  (none)"
        )
        prompts = get_encoder_prompts("detect_drift")
        user_content = _build_user_message(
            "detect_drift",
            active_core_intent=active_core_intent or "(none)",
            active_event_updates=active_event_updates_block,
            user_message=user_message,
            agent_response=agent_response,
            recent_turns=recent_turns,
        )
        input_messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=input_messages,
                response_model=DetectDriftResponse,
                temperature=0.3,
                max_tokens=4000,
                op="detect_drift",
            )
            decision = result.decision
            if decision not in ("update_existing", "create_new_branch"):
                decision = "update_existing"
            return (decision, result.reason)
        except Exception as e:
            logger.error("Error in detect_drift: %s", e)
            return ("update_existing", None)

    def should_create_new_event(
        self,
        user_message: str,
        agent_response: str,
        ets_traces: Optional[List[str]] = None,
        recent_turns: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Use LLM to decide: create a new engram vs append to ETS (weak traces).
        Returns (should_create, reason).
        """
        ets_traces = ets_traces or []
        ets_traces_block = "\n".join(f"- {t}" for t in ets_traces) if ets_traces else "(none)"
        recent_turns = (recent_turns or "").strip() or "(No previous turns)"

        prompts = get_encoder_prompts("should_create_new_event")
        user_content = _build_user_message(
            "should_create_new_event",
            ets_traces_block=ets_traces_block,
            user_message=user_message,
            agent_response=agent_response,
            recent_turns=recent_turns,
        )
        input_messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=input_messages,
                response_model=ShouldCreateNewEventResponse,
                temperature=0.3,
                max_tokens=4000,
                op="should_create_new_event",
            )
            return (bool(result.should_create), result.reason)
        except Exception as e:
            logger.error("Error deciding new event creation: %s", e)
            return (False, None)

    def generate_new_event(
        self,
        user_message: str,
        agent_response: str,
        recent_turns: Optional[str] = None,
        drift_from_intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Use LLM to create a new engram from scratch. Returns event dict."""
        recent_turns = (recent_turns or "").strip() or "(No previous turns)"
        if drift_from_intent:
            drift_context_block = (
                f"**IMPORTANT — Drift context**: This memory is being created because the "
                f"conversation diverged from a prior topic: \"{drift_from_intent}\".\n"
                f"Focus core_intent on what is genuinely NEW in this turn.\n"
                f"Recent turns are colored by the prior topic — use them for background only, "
                f"not as anchoring material for the new core_intent."
            )
        else:
            drift_context_block = ""
        prompts = get_encoder_prompts("generate_new_event")
        user_content = _build_user_message(
            "generate_new_event",
            user_message=user_message,
            agent_response=agent_response,
            recent_turns=recent_turns,
            drift_context_block=drift_context_block,
        )
        input_messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=input_messages,
                response_model=GenerateNewEventResponse,
                temperature=0.3,
                max_tokens=4000,
                op="generate_new_event",
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            updates = result.updates or []
            return {
                "core_intent": result.core_intent or "New conversation topic",
                "updates": updates if isinstance(updates, list) else [updates] if updates else [],
                "relevance_score": 1.0,
                "reinforcement_count": 0,
                "created_at": now_iso,
                "last_touched": now_iso,
                "last_decay_applied_at": now_iso,
            }
        except Exception as e:
            logger.error("Error generating new event: %s", e)
            now_iso = datetime.now(timezone.utc).isoformat()
            return {
                "core_intent": f"Discussion about: {user_message[:50]}...",
                "updates": [user_message[:100]] if user_message else [],
                "relevance_score": 1.0,
                "reinforcement_count": 0,
                "created_at": now_iso,
                "last_touched": now_iso,
                "last_decay_applied_at": now_iso,
            }

    def maybe_append_to_ets(
        self,
        user_message: str,
        agent_response: str,
        existing_traces: Optional[List[str]] = None,
        recent_turns: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Decide if turn is meaningful enough for ETS; generate trace summary if so."""
        existing_traces = existing_traces or []
        traces_str = "\n".join(f"- {t}" for t in existing_traces) if existing_traces else "(none)"
        recent_turns = (recent_turns or "").strip() or "(No previous turns)"

        prompts = get_encoder_prompts("maybe_append_to_ets")
        user_content = _build_user_message(
            "maybe_append_to_ets",
            existing_traces=traces_str,
            recent_turns=recent_turns,
            user_message=user_message,
            agent_response=agent_response,
        )
        input_messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=input_messages,
                response_model=MaybeAppendToEtsResponse,
                temperature=0.3,
                max_tokens=4000,
                op="maybe_append_to_ets",
            )
            if result.store and result.trace_summary and isinstance(result.trace_summary, str) and result.trace_summary.strip():
                return True, result.trace_summary.strip()
            return False, None
        except Exception as e:
            logger.error("Error in maybe_append_to_ets: %s", e)
            return False, None

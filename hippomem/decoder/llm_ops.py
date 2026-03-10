"""
LLM Operations for the decoder — C1 continuation check and final synthesis.

Prompts loaded from hippomem/prompts/decoder.yaml.
"""
import logging
from typing import Dict, Any, List, Optional

from hippomem.infra.llm import LLMService
from hippomem.prompts import get_decoder_prompts
from hippomem.decoder.schemas import ContinuationResult, SynthesisResponse

logger = logging.getLogger(__name__)


class DecoderLLMOps:
    """Thin wrapper around LLMService for decoder-specific structured calls."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm = llm_service

    def check_continuation(
        self,
        current_message: str,
        conversation_window: str,
        current_event: Dict[str, Any],
    ) -> ContinuationResult:
        """
        C1: Check if the message continues the current event or shifts topic.

        Args:
            current_message: The new user message.
            conversation_window: Last N turns as "User: ...\\nAssistant: ..."
            current_event: Dict with at least core_intent (active_events[0]).

        Returns:
            ContinuationResult with decision, confidence, reasoning.
        """
        prompts = get_decoder_prompts("continuation_check")
        core_intent = current_event.get("core_intent", "") or ""
        prompt = prompts["user_template"].format(
            conversation_window=conversation_window or "(no prior conversation)",
            core_intent=core_intent,
            user_message=current_message,
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat_structured(
            messages=messages,
            response_model=ContinuationResult,
            temperature=0.2,
            max_tokens=4000,
            op="continuation_check",
        )

    def synthesize(
        self,
        events_for_synthesis: List[Dict[str, Any]],
        id_to_uuid: Dict[str, str],
        user_message: str,
        self_profile: Optional[str] = None,
        linked_entities: Optional[List[Dict[str, Any]]] = None,
        entity_id_to_uuid: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Final synthesis: call LLM to produce a memory context string.

        entity_id_to_uuid: Optional N-prefix -> entity UUID (e.g. {"N1": uuid1}). Used to
            resolve events_used entries for linked entities so used_entity_ids is populated.

        Returns:
            {"synthesized_context": str, "used_engram_ids": List[str], "used_entity_ids": List[str], "reasoning": str}
        """
        prompts = get_decoder_prompts("synthesis")
        user_content = self._build_synthesis_prompt(
            events_for_synthesis, user_message, prompts,
            self_profile=self_profile,
            linked_entities=linked_entities,
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        result = self.llm.chat_structured(
            messages=messages,
            response_model=SynthesisResponse,
            temperature=0.3,
            max_tokens=4000,
            op="synthesis",
        )
        result_dict = result.model_dump()
        events_used = result_dict.get("events_used") or []
        entity_id_to_uuid = entity_id_to_uuid or {}

        used_engram_ids = []
        used_entity_ids = []
        for eu in events_used:
            eid = eu.get("engram_id")
            if not eid:
                continue
            if eid in id_to_uuid:
                used_engram_ids.append(id_to_uuid[eid])
            elif eid in entity_id_to_uuid:
                used_entity_ids.append(entity_id_to_uuid[eid])

        return {
            "synthesized_context": result_dict.get("synthesized_context", ""),
            "used_engram_ids": used_engram_ids,
            "used_entity_ids": used_entity_ids,
            "reasoning": result_dict.get("reasoning", ""),
        }

    def _format_event_block(self, event: Dict[str, Any]) -> str:
        """Format a single event for the synthesis events_block."""
        event_id = event.get("event_id", "")
        event_kind = event.get("event_kind", "episode")

        if event_kind == "entity":
            entity_type = event.get("entity_type", "entity")
            name = event.get("core_intent", "")
            summary = event.get("summary_text") or ""
            facts = event.get("updates") or []
            lines = [f"[{event_id} - ENTITY: {entity_type}]", f"Name: {name}"]
            if summary:
                lines.append(f"Profile: {summary}")
            if facts:
                lines.append("Known facts:")
                lines.extend(f"- {f}" for f in facts)
            return "\n".join(lines)

        # Episodic format
        core_intent = event.get("core_intent", "")
        updates = event.get("updates") or []
        lines = [f"[{event_id}] Topic: {core_intent}"]
        if updates:
            lines.append("Updates:")
            lines.extend(f"- {u}" for u in updates)
        return "\n".join(lines)

    def _build_synthesis_prompt(
        self,
        events: List[Dict[str, Any]],
        user_message: str,
        prompts: Dict[str, Any],
        self_profile: Optional[str] = None,
        linked_entities: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        blocks = [self._format_event_block(event) for event in events]
        events_block = "\n\n".join(blocks)

        if linked_entities:
            entity_blocks = []
            for i, entity in enumerate(linked_entities):
                entity_with_id = {**entity, "event_id": f"N{i + 1}"}
                entity_blocks.append(self._format_event_block(entity_with_id))
            events_block += "\n\n**Linked Entity Profiles:**\n\n" + "\n\n".join(entity_blocks)

        self_profile_block = ""
        if self_profile:
            self_profile_block = f"**User Identity Profile:**\n{self_profile}\n\n---\n\n"
        return prompts["user_template"].format(
            user_message=user_message,
            events_block=events_block,
            self_profile_block=self_profile_block,
        )

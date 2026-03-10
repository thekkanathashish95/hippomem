"""
LLM operations for entity extraction.
Prompts loaded from hippomem/prompts/entity.yaml.
"""
import logging
from typing import List

from hippomem.infra.llm import LLMService
from hippomem.prompts import get_entity_prompts
from hippomem.memory.entity.schemas import EntityExtractionResult, DisambiguationResult

logger = logging.getLogger(__name__)


class EntityLLMOps:
    """LLM operations for entity extraction and disambiguation."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm = llm_service

    def extract_entities(
        self,
        user_message: str,
        agent_response: str,
        recent_turns: str,
    ) -> EntityExtractionResult:
        """Extract named entities from the current turn."""
        prompts = get_entity_prompts("extract_entities")
        user_content = prompts["user_template"].format(
            recent_turns=recent_turns or "(none)",
            user_message=user_message,
            agent_response=agent_response,
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            return self.llm.chat_structured(
                messages=messages,
                response_model=EntityExtractionResult,
                temperature=0.1,
                max_tokens=4000,
                op="extract_entities",
            )
        except Exception as e:
            logger.error("Entity extraction LLM call failed: %s", e)
            return EntityExtractionResult(entities=[])

    def disambiguate_entity(
        self,
        new_name: str,
        entity_type: str,
        mention_context: str,
        candidates: List[dict],  # list of {name, facts, entity_uuid}
    ) -> DisambiguationResult:
        """Determine if a new entity name matches an existing candidate."""
        prompts = get_entity_prompts("disambiguate_entity")
        blocks = []
        for i, c in enumerate(candidates, 1):
            facts_str = "\n".join(f"  - {f}" for f in (c.get("facts") or []))
            blocks.append(f"candidate_{i}: {c['name']}\n{facts_str or '  (no facts)'}")
        candidates_block = "\n\n".join(blocks) or "(no candidates)"
        user_content = prompts["user_template"].format(
            new_name=new_name,
            entity_type=entity_type,
            mention_context=mention_context,
            candidates_block=candidates_block,
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            return self.llm.chat_structured(
                messages=messages,
                response_model=DisambiguationResult,
                temperature=0.1,
                max_tokens=4000,
                op="disambiguate_entity",
            )
        except Exception as e:
            logger.error("Entity disambiguation LLM call failed: %s", e)
            return DisambiguationResult(match=None, confidence=0.0, reason="LLM error")

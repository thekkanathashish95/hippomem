"""
LLM Operations for consolidation — entity profile enrichment, episode compression,
and persona narrative generation.

Prompts loaded from hippomem/prompts/consolidator.yaml.
"""
import logging
from typing import Dict, Any, List, Optional

from pydantic import BaseModel, Field

from hippomem.infra.llm import LLMService
from hippomem.prompts import get_consolidator_prompts

logger = logging.getLogger(__name__)


class UpdateEntityProfileResponse(BaseModel):
    """LLM response: merged facts and summary for an entity profile."""

    merged_facts: List[str] = Field(default_factory=list)
    summary_text: str = ""


class ConsolidateEpisodeResponse(BaseModel):
    """LLM response: compressed update list for an episode."""

    merged_updates: List[str] = Field(default_factory=list)


class GenerateIdentitySummaryResponse(BaseModel):
    """LLM response: concise identity narrative from grouped self traits."""

    identity_summary: str = ""


class ConsolidationLLMOps:
    """LLM operations specific to memory consolidation."""

    def __init__(self, llm_service: LLMService) -> None:
        self.llm = llm_service

    def generate_identity_summary(
        self,
        traits_by_category: Dict[str, List[str]],
    ) -> str:
        """Generate a concise identity narrative from grouped active traits."""
        prompts = get_consolidator_prompts("generate_identity_summary")
        traits_block = "\n".join(
            f"{category.replace('_', ' ').title()}:\n"
            + "\n".join(f"  - {t}" for t in traits)
            for category, traits in traits_by_category.items()
        )
        user_content = prompts["user_template"].format(traits_block=traits_block)
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=messages,
                response_model=GenerateIdentitySummaryResponse,
                temperature=0.3,
                max_tokens=4000,
                op="generate_identity_summary",
            )
            return result.identity_summary or ""
        except Exception as e:
            logger.error("generate_identity_summary failed: %s", e)
            return ""

    def update_entity_profile(
        self,
        canonical_name: str,
        entity_type: str,
        consolidated_facts: List[str],
        pending_facts: List[str],
        existing_summary: Optional[str],
    ) -> Dict[str, Any]:
        """Merge pending facts into consolidated baseline and regenerate summary."""
        prompts = get_consolidator_prompts("update_entity_profile")
        consolidated_str = "\n".join(f"- {f}" for f in consolidated_facts) or "(none)"
        pending_str = "\n".join(f"- {f}" for f in pending_facts) or "(none)"
        user_content = prompts["user_template"].format(
            canonical_name=canonical_name,
            entity_type=entity_type,
            consolidated_facts=consolidated_str,
            pending_facts=pending_str,
            existing_summary=existing_summary or "(none)",
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=messages,
                response_model=UpdateEntityProfileResponse,
                temperature=0.3,
                max_tokens=4000,
                op="update_entity_profile",
            )
            return {
                "merged_facts": result.merged_facts or [],
                "summary_text": result.summary_text or "",
            }
        except Exception as e:
            logger.error("update_entity_profile LLM call failed: %s", e)
            return {
                "merged_facts": consolidated_facts + pending_facts,
                "summary_text": existing_summary or "",
            }

    def consolidate_episode_updates(
        self,
        core_intent: str,
        consolidated_updates: List[str],
        pending_updates: List[str],
    ) -> Dict[str, Any]:
        """Compress pending episode updates into the consolidated baseline."""
        prompts = get_consolidator_prompts("consolidate_episode_updates")
        consolidated_str = "\n".join(f"- {u}" for u in consolidated_updates) or "(none)"
        pending_str = "\n".join(f"- {u}" for u in pending_updates) or "(none)"
        user_content = prompts["user_template"].format(
            core_intent=core_intent,
            consolidated_updates=consolidated_str,
            pending_updates=pending_str,
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            result = self.llm.chat_structured(
                messages=messages,
                response_model=ConsolidateEpisodeResponse,
                temperature=0.3,
                max_tokens=4000,
                op="consolidate_episode_updates",
            )
            return {"merged_updates": result.merged_updates or []}
        except Exception as e:
            logger.error("consolidate_episode_updates LLM call failed: %s", e)
            return {"merged_updates": consolidated_updates + pending_updates}

"""
LLM Operations for consolidation — cluster summary generation and entity profile enrichment.

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
        all_facts: List[str],
        existing_summary: Optional[str],
    ) -> Dict[str, Any]:
        """Merge facts and generate summary_text for an entity profile."""
        prompts = get_consolidator_prompts("update_entity_profile")
        facts_str = "\n".join(f"- {f}" for f in all_facts) or "(none)"
        user_content = prompts["user_template"].format(
            canonical_name=canonical_name,
            entity_type=entity_type,
            all_facts=facts_str,
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
            return {"merged_facts": all_facts, "summary_text": existing_summary or ""}

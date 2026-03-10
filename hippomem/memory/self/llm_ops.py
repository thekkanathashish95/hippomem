"""LLM operations for self extraction."""
import logging
from typing import List, Dict

from hippomem.infra.llm import LLMService
from hippomem.prompts import get_self_prompts
from hippomem.memory.self.schemas import SelfExtractionResult

logger = logging.getLogger(__name__)


class SelfLLMOps:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm = llm_service

    def extract_self_candidates(
        self,
        user_message: str,
        existing_traits: List[Dict[str, str]],
        recent_turns: str = "",
    ) -> SelfExtractionResult:
        """
        Classify self-signals in the current user message against known traits.
        The LLM sees existing trait values + evidence counts and returns
        action-tagged candidates (new / update / confirm).
        Returns empty candidates list when nothing actionable is found.
        """
        prompts = get_self_prompts("extract_self_candidates")
        existing_traits_block = (
            "\n".join(
                f"  {t['category']} | {t['key']}: {t['value']}  (seen {t['evidence_count']}x)"
                for t in existing_traits
            )
            or "  (none yet)"
        )
        user_content = prompts["user_template"].format(
            user_message=user_message,
            recent_turns=recent_turns or "  (no prior turns)",
            existing_traits_block=existing_traits_block,
        )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content},
        ]
        try:
            return self.llm.chat_structured(
                messages=messages,
                response_model=SelfExtractionResult,
                temperature=0.1,
                max_tokens=4000,
                op="extract_self_candidates",
            )
        except Exception as e:
            logger.error("Self extraction LLM call failed: %s", e)
            return SelfExtractionResult(candidates=[])

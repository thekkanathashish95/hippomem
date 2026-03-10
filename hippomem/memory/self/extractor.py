"""Orchestrates self-signal extraction and trait accumulation after each encode turn."""
import logging
from typing import List, Tuple, TYPE_CHECKING

from sqlalchemy.orm import Session

from hippomem.memory.self.llm_ops import SelfLLMOps
from hippomem.memory.self.service import get_existing_traits, accumulate_traits
from hippomem.decoder.context_builder import format_recent_turns

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SELF_EXTRACT_TURNS = 3  # how many prior turns to include as context


class SelfExtractor:
    """
    Orchestrates self-signal extraction and trait accumulation after each encode turn.
    Injected into MemoryEncoder when enable_self_memory=True.
    """

    def __init__(self, llm_ops: SelfLLMOps) -> None:
        self.llm_ops = llm_ops

    def extract_and_accumulate(
        self,
        user_id: str,
        user_message: str,
        conversation_history: List[Tuple[str, str]],
        db: Session,
    ) -> None:
        existing_traits = get_existing_traits(user_id, db)
        recent_turns = format_recent_turns(conversation_history, _SELF_EXTRACT_TURNS)
        result = self.llm_ops.extract_self_candidates(
            user_message=user_message,
            existing_traits=existing_traits,
            recent_turns=recent_turns,
        )
        logger.debug("extract: candidates=%d", len(result.candidates))
        if not result.candidates:
            return  # fast path — no self-signals found
        upserted, newly_active = accumulate_traits(user_id, result.candidates, db)
        logger.debug("traits: upserted=%d newly_active=%d", upserted, newly_active)
        db.commit()

"""
Pydantic schemas for decoder LLM responses (C1 continuation check + synthesis).
"""
from dataclasses import dataclass, field
from typing import List

from pydantic import BaseModel, Field


class ContinuationResult(BaseModel):
    """Result of C1 continuation check."""

    decision: str = Field(description="CONTINUE | SHIFT | UNCERTAIN")
    confidence: float = Field(ge=0, le=1, description="Confidence 0-1")
    reasoning: str = Field(default="", description="Brief explanation")


class EventUsed(BaseModel):
    """Event used in synthesis with role assignment."""

    engram_id: str = Field(
        description="Display ID from context (e.g. E1, D1, L1, N1)",
        alias="event_id",
    )
    role: str = Field(description="primary | supporting | associative")

    model_config = {"populate_by_name": True}


class SynthesisResponse(BaseModel):
    """
    Required structured output from the context synthesis LLM.
    LLM returns engram_ids (E1, D1) with roles; synthesizer maps to UUIDs before returning.
    """

    synthesized_context: str = Field(
        description="Concise prose (4-8 lines) with relevant context about the user, in third person (e.g. 'The user was...', 'They had decided...')."
    )
    events_used: List[EventUsed] = Field(
        default_factory=list,
        description="Events that were relevant and used, with role (primary/supporting/associative).",
    )
    reasoning: str = Field(
        description="Brief explanation of why these events were chosen and how they relate to the user's message."
    )


@dataclass
class DecodeResult:
    """
    Return value of decode().

    Pass this object into encode() so hippomem can update the correct events.

    Attributes:
        context: Formatted memory context string. Pass directly to your LLM prompt.
        used_engram_ids: Episode/summary engram UUIDs used in synthesis (internal state for encode).
        used_entity_ids: Entity engram UUIDs that were surfaced in synthesis (N-prefix in prompt).
        reasoning: Why these events were selected (for debugging).
        synthesized_context: Raw synthesized text (same as context without markdown wrapper).
        turn_id: UUID linking this decode to its corresponding encode row.
    """
    context: str
    used_engram_ids: List[str]
    reasoning: str
    synthesized_context: str
    used_entity_ids: List[str] = field(default_factory=list)
    turn_id: str = ""

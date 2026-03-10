"""Pydantic schemas for self extraction."""
from pydantic import BaseModel, Field
from typing import List, Literal


class ExtractedSelfCandidate(BaseModel):
    category: str  # one of: stable_attribute|goal|personality|preference|constraint|project|social
    key: str  # normalized snake_case identifier
    value: str  # the trait content
    action: Literal["new", "update", "confirm"]
    # new     = key not seen before
    # update  = same key but value has changed (evolution detected)
    # confirm = same key, same value; just strengthen evidence
    confidence_estimate: float = Field(ge=0.0, le=1.0)


class SelfExtractionResult(BaseModel):
    candidates: List[ExtractedSelfCandidate] = Field(default_factory=list)
    # Empty list = no durable self-signals found in this turn (fast path)

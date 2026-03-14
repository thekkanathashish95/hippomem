"""Pydantic schemas for self extraction."""
from pydantic import BaseModel, Field
from typing import List


class ExtractedSelfCandidate(BaseModel):
    category: str  # one of: stable_attribute|goal|personality|preference|constraint|project|social
    key: str  # normalized snake_case identifier
    value: str  # the trait content
    confidence_estimate: float = Field(ge=0.0, le=1.0)


class SelfExtractionResult(BaseModel):
    candidates: List[ExtractedSelfCandidate] = Field(default_factory=list)
    # Empty list = no durable self-signals found in this turn (fast path)

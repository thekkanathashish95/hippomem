"""Pydantic schemas for entity extraction."""
from typing import List, Optional
from pydantic import BaseModel


class ExtractedEntity(BaseModel):
    canonical_name: str
    entity_type: str        # person | organization | place | project | pet | tool | other
    mention_type: str       # protagonist | subject | referenced
    facts: List[str]
    significant: bool
    hint_id: Optional[str] = None   # "H1", "H2", ... if matched to a decoder hint; null for new entities


class EntityExtractionResult(BaseModel):
    entities: List[ExtractedEntity] = []


class DisambiguationResult(BaseModel):
    match: Optional[str] = None   # "candidate_N" string or None (new entity)
    confidence: float = 0.0
    reason: str = ""

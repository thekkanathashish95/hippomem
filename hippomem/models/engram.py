"""
Engram - Source of truth for all memory content.
Vectors live in FAISS per-user index. All engrams are persisted here on create.
"""
import enum
import uuid
from sqlalchemy import Column, String, DateTime, UniqueConstraint, Integer, JSON, Float, Text
from sqlalchemy.sql import func

from hippomem.db.base import Base


class EngramKind(str, enum.Enum):
    EPISODE = "episode"
    SUMMARY = "summary"
    ENTITY = "entity"    # reserved — v1.5
    PERSONA = "persona"  # reserved — future


class Engram(Base):
    """
    Engram store — source of truth for all memory content.
    Engrams are persisted on create (not only on demotion).
    last_updated_at = last time this engram was used in synthesis.
    """
    __tablename__ = "engrams"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    engram_id = Column(String, nullable=False)
    content_hash = Column(String, nullable=True)

    engram_kind = Column(String, default=EngramKind.EPISODE.value, nullable=False)
    entity_type = Column(String, nullable=True)
    # null for EPISODE/SUMMARY; set for ENTITY nodes
    # values: "person", "organization", "place", "project", "pet"

    # Content
    core_intent = Column(String, nullable=True)
    updates = Column(JSON, nullable=True)           # List[str]
    summary_text = Column(Text, nullable=True)     # For SUMMARY / future ENTITY nodes

    reinforcement_count = Column(Integer, nullable=True)

    # Decay
    relevance_score = Column(Float, default=1.0, nullable=True)
    last_decay_applied_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_updated_at = Column(DateTime(timezone=True), nullable=True)  # last used in synthesis

    __table_args__ = (
        UniqueConstraint("user_id", "engram_id", name="uq_engram"),
    )

"""
EngramLink - Unified link model for navigational edges and entity mentions.
Replaces EventEventEdge + EventEntityLink. Used for graph traversal and consolidation.
"""
import enum
import uuid
from sqlalchemy import Column, String, DateTime, Float, UniqueConstraint
from sqlalchemy.sql import func

from hippomem.db.base import Base


class LinkKind(str, enum.Enum):
    SIMILARITY = "similarity"
    TEMPORAL = "temporal"
    RETRIEVAL = "retrieval"
    TRIADIC = "triadic"
    MENTION = "mention"


class MentionType(str, enum.Enum):
    PROTAGONIST = "protagonist"
    SUBJECT = "subject"
    REFERENCED = "referenced"


class EngramLink(Base):
    """
    Link in the engram graph. Supports navigational links (SIMILARITY, TEMPORAL,
    RETRIEVAL, TRIADIC) with weight, and MENTION links (episode→entity) with mention_type.
    Scope: user_id (global per user).
    """
    __tablename__ = "engram_links"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    link_kind = Column(String, nullable=False)
    weight = Column(Float, default=0.0, nullable=True)
    mention_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "source_id", "target_id", "link_kind", name="uq_engram_link"),
    )

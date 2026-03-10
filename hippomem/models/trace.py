"""
Trace - Pre-memory layer for weak conversational traces.
FIFO fixed-capacity per (user_id, session_id) scope.
Not part of working memory, synthesis, or scoring — promotion-only.
"""
import uuid
from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.sql import func

from hippomem.db.base import Base


class Trace(Base):
    """
    Weak conversational traces that may become engrams if reinforced.
    Fixed-capacity FIFO per (user_id, session_id) scope.
    """
    __tablename__ = "traces"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_traces_scope", "user_id", "session_id"),
    )

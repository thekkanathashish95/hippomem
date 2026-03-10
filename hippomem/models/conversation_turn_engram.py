"""
ConversationTurnEngram - Junction table linking conversation turns to engrams.
Enables retrieval of raw message pairs given an engram/entity UUID.
"""
import uuid
from sqlalchemy import Column, String, Index

from hippomem.db.base import Base


class ConversationTurnEngram(Base):
    """
    Links a ConversationTurn to one or more engrams.
    link_type:
      "decoded" — engram was surfaced by decode() and injected into this turn's context
      "encoded" — engram that this turn was written into (may be new or updated)
    No hard FK on engram_id — engrams can be independently deleted without cascading.
    """
    __tablename__ = "conversation_turn_engrams"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    turn_id = Column(String, nullable=False)    # ConversationTurn.id
    engram_id = Column(String, nullable=False)  # Engram.engram_id (UUID)
    link_type = Column(String, nullable=False)  # "decoded" | "encoded"
    user_id = Column(String, nullable=False)    # denormalized for user-scoped queries

    __table_args__ = (
        Index("ix_cte_engram_user", "engram_id", "user_id"),
        Index("ix_cte_turn", "turn_id"),
    )

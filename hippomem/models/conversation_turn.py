"""
ConversationTurn - Raw conversation pair storage.
One row per encode() call — stores user/assistant message pair with linked memory context.
"""
import uuid
from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.sql import func

from hippomem.db.base import Base


class ConversationTurn(Base):
    """
    Raw conversation turn persisted as a side effect of encode().
    turn_id links to the corresponding LLMInteraction decode/encode rows.
    """
    __tablename__ = "conversation_turns"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=True)
    turn_id = Column(String, nullable=True)   # links to LLMInteraction.turn_id
    user_message = Column(Text, nullable=False)
    assistant_response = Column(Text, nullable=False)
    memory_context = Column(Text, nullable=True)  # synthesized_context injected into LLM
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_conv_turns_user", "user_id", "created_at"),
        Index("ix_conv_turns_session", "user_id", "session_id", "created_at"),
        Index("ix_conv_turns_turn_id", "turn_id"),
    )

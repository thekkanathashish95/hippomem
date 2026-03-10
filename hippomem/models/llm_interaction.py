"""
ORM models for LLM call tracing — Inspector persistence.
"""
import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, JSON, Text
from sqlalchemy.sql import func

from hippomem.db.base import Base


class LLMInteraction(Base):
    """One row per decode / encode / consolidate operation."""

    __tablename__ = "llm_interactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    operation = Column(String, nullable=False)  # "decode" | "encode" | "consolidate"
    call_count = Column(Integer, default=0)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    total_latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    turn_id = Column(String, nullable=True, index=True)  # links decode + encode rows
    session_id = Column(String, nullable=True, index=True)  # for scoped DB fallback
    output = Column(JSON, nullable=True)  # generic operation output


class LLMCallLog(Base):
    """One row per individual LLM call, FK'd to LLMInteraction."""

    __tablename__ = "llm_call_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    interaction_id = Column(
        String, ForeignKey("llm_interactions.id"), nullable=False, index=True
    )
    user_id = Column(String, nullable=False, index=True)
    op = Column(String, nullable=False)
    model = Column(String, nullable=False)
    messages = Column(JSON, nullable=False)
    raw_response = Column(Text, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    step_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

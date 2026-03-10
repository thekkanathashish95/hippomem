"""TurnStatus - per-turn decode/encode phase tracking for real-time progress and polling fallback."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text, Index

from hippomem.db.base import Base


class TurnStatus(Base):
    __tablename__ = "turn_status"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    turn_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    phase = Column(String, nullable=False)   # 'decode' | 'encode'
    status = Column(String, nullable=False)  # 'running' | 'done' | 'error'
    current_step = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_msg = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_turn_status_turn_id", "turn_id"),
        Index("ix_turn_status_user", "user_id", "started_at"),
    )

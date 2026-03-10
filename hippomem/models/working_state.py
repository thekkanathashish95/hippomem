"""
WorkingState - Tracks active and dormant event UUIDs per user (and optionally per session).
Stores UUID lists only; EventStore holds all content.
"""
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Column, String, DateTime, UniqueConstraint
from sqlalchemy.sql import func

from hippomem.db.base import Base
from hippomem.schemas.working_state import WorkingStateData, WorkingStateDataType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, Query


class WorkingState(Base):
    """
    Working memory state for a user or session.
    state_data is WorkingStateData (UUIDs only; EventStore is source of truth).
    """
    __tablename__ = "working_states"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True, index=True)

    state_data = Column(WorkingStateDataType, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # One working state per user, or per (user, session) pair
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_working_state_scope"),
    )

    @classmethod
    def for_scope(cls, db: "Session", user_id: str, session_id: Optional[str]) -> "Query":
        """
        Return a query filtered to the given user/session scope.

        Usage::

            ws = WorkingState.for_scope(db, user_id, session_id).first()
        """
        q = db.query(cls).filter(cls.user_id == user_id)
        if session_id is not None:
            return q.filter(cls.session_id == session_id)
        return q.filter(cls.session_id.is_(None))

    @classmethod
    def load(
        cls,
        db: "Session",
        user_id: str,
        session_id: Optional[str],
    ) -> Optional[WorkingStateData]:
        """Load working state data for this scope, or None if not found."""
        ws = cls.for_scope(db, user_id, session_id).first()
        return ws.state_data if ws else None

    @classmethod
    def load_or_create(
        cls,
        db: "Session",
        user_id: str,
        session_id: Optional[str],
    ) -> WorkingStateData:
        """
        Load working state data for this scope.
        If no record exists, return a fresh empty WorkingStateData (not yet persisted).
        """
        ws = cls.for_scope(db, user_id, session_id).first()
        if ws:
            return ws.state_data
        return WorkingStateData(
            working_state_id=f"ws_{user_id}_{session_id or 'global'}",
            last_updated=datetime.now(timezone.utc).isoformat(),
            active_event_uuids=[],
            recent_dormant_uuids=[],
        )

    @classmethod
    def persist(
        cls,
        db: "Session",
        user_id: str,
        session_id: Optional[str],
        state_data: WorkingStateData,
    ) -> None:
        """
        Upsert working state for this scope and commit.
        Creates a new record if one does not exist yet.
        """
        ws = cls.for_scope(db, user_id, session_id).first()
        if ws:
            ws.state_data = state_data
        else:
            ws = cls(
                id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                state_data=state_data,
            )
            db.add(ws)
        db.commit()

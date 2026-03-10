"""
Trace Store Service — pre-memory layer operations.
FIFO fixed-capacity per (user_id, session_id) scope.
"""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session

from hippomem.models.trace import Trace

logger = logging.getLogger(__name__)

DEFAULT_MAX_ETS_ENTRIES = 8


def get_traces(
    user_id: str,
    session_id: Optional[str],
    db: Session,
) -> List[str]:
    """Load traces for scope, ordered by created_at ASC (FIFO order)."""
    query = db.query(Trace).filter(Trace.user_id == user_id)
    if session_id:
        query = query.filter(Trace.session_id == session_id)
    else:
        query = query.filter(Trace.session_id.is_(None))
    traces = query.order_by(Trace.created_at.asc()).all()
    return [t.content for t in traces]


def append_trace(
    user_id: str,
    session_id: Optional[str],
    content: str,
    db: Session,
    max_size: int = DEFAULT_MAX_ETS_ENTRIES,
) -> None:
    """Add trace. Evict oldest if at or over capacity (FIFO)."""
    if not content or not content.strip():
        return

    query = db.query(Trace).filter(Trace.user_id == user_id)
    if session_id:
        query = query.filter(Trace.session_id == session_id)
    else:
        query = query.filter(Trace.session_id.is_(None))

    count = query.count()
    if count >= max_size:
        oldest = query.order_by(Trace.created_at.asc()).first()
        if oldest:
            db.delete(oldest)
            db.flush()

    db.add(Trace(
        user_id=user_id,
        session_id=session_id,
        content=content.strip(),
    ))
    db.commit()



def copy_traces(
    from_user_id: str,
    from_session_id: Optional[str],
    to_user_id: str,
    to_session_id: Optional[str],
    db: Session,
) -> int:
    """Copy all traces from source scope to target scope. Returns count copied."""
    query = db.query(Trace).filter(Trace.user_id == from_user_id)
    if from_session_id:
        query = query.filter(Trace.session_id == from_session_id)
    else:
        query = query.filter(Trace.session_id.is_(None))

    source_traces = query.order_by(Trace.created_at.asc()).all()
    for t in source_traces:
        db.add(Trace(
            user_id=to_user_id,
            session_id=to_session_id,
            content=t.content,
        ))
    if source_traces:
        db.commit()
    return len(source_traces)

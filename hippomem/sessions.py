"""
Session management — initialize working state and snapshot global memory to a session.

Functions here accept an already-open DB session; callers (MemoryService) own the
session lifecycle (open / close / commit on error).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from hippomem.models.working_state import WorkingState
from hippomem.schemas.working_state import WorkingStateData
from hippomem.memory.traces import service as traces_svc

logger = logging.getLogger(__name__)


def initialize_session(
    user_id: str,
    session_id: Optional[str],
    db: Session,
) -> Dict[str, Any]:
    """
    Create empty working state for a new user/session scope.
    Returns existing state (as a dict) if already initialized.
    """
    existing = WorkingState.for_scope(db, user_id, session_id).first()
    if existing:
        return existing.state_data.model_dump() if existing.state_data else {}

    state_data = WorkingStateData(
        working_state_id=f"ws_{user_id}_{session_id or 'global'}",
        last_updated=datetime.now(timezone.utc).isoformat(),
        active_event_uuids=[],
        recent_dormant_uuids=[],
    )
    ws = WorkingState(
        id=str(uuid.uuid4()),
        user_id=user_id,
        session_id=session_id,
        state_data=state_data,
    )
    db.add(ws)
    db.commit()
    return state_data.model_dump()


def snapshot_to_session(
    user_id: str,
    new_session_id: str,
    db: Session,
) -> None:
    """
    Copy global (session_id=None) memory state to a new session at session start.
    Seeds the new session with the user's existing long-term context.
    """
    global_ws = WorkingState.for_scope(db, user_id, None).first()

    if not global_ws:
        initialize_session(user_id, new_session_id, db)
        return

    src = global_ws.state_data
    if not isinstance(src, WorkingStateData):
        src = WorkingStateData.model_validate(src or {})

    new_state = WorkingStateData(
        working_state_id=f"ws_{user_id}_{new_session_id}",
        last_updated=datetime.now(timezone.utc).isoformat(),
        active_event_uuids=list(src.active_event_uuids),
        recent_dormant_uuids=list(src.recent_dormant_uuids),
    )
    ws = WorkingState(
        id=str(uuid.uuid4()),
        user_id=user_id,
        session_id=new_session_id,
        state_data=new_state,
    )
    db.add(ws)

    ets_count = traces_svc.copy_traces(user_id, None, user_id, new_session_id, db)
    db.commit()
    logger.info(
        "Snapshotted global memory to session %s: %d active, %d ETS traces",
        new_session_id, len(new_state.active_event_uuids), ets_count,
    )

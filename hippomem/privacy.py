"""User deletion and export — GDPR-facing operations."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from hippomem.models.conversation_turn import ConversationTurn
from hippomem.models.conversation_turn_engram import ConversationTurnEngram
from hippomem.models.engram import Engram
from hippomem.models.engram_link import EngramLink
from hippomem.models.llm_interaction import LLMCallLog, LLMInteraction
from hippomem.models.self_trait import SelfTrait
from hippomem.models.trace import Trace
from hippomem.models.turn_status import TurnStatus
from hippomem.models.working_state import WorkingState

logger = logging.getLogger(__name__)

EXPORT_SCHEMA_VERSION = 1


def _safe_user_filename(user_id: str) -> str:
    return re.sub(r"[/\\:]+", "_", user_id)


def delete_user_data(
    user_id: str,
    db: Session,
    vector_dir: str,
    bm25_invalidate=None,
) -> dict[str, int]:
    """
    Purge every row and the FAISS index for user_id.
    Returns counts of deleted rows per table.
    """
    counts: dict[str, int] = {}

    def _wipe(model) -> int:
        q = db.query(model).filter(model.user_id == user_id)
        n = q.delete(synchronize_session=False)
        counts[model.__tablename__] = n
        return n

    _wipe(LLMCallLog)
    _wipe(LLMInteraction)
    _wipe(ConversationTurnEngram)
    _wipe(ConversationTurn)
    _wipe(TurnStatus)
    _wipe(Trace)
    _wipe(SelfTrait)
    _wipe(EngramLink)
    _wipe(WorkingState)
    _wipe(Engram)
    db.commit()

    index_path = Path(vector_dir) / f"{_safe_user_filename(user_id)}.index"
    if index_path.exists():
        index_path.unlink()
        counts["faiss_index"] = 1
    else:
        counts["faiss_index"] = 0

    if bm25_invalidate is not None:
        bm25_invalidate(user_id)

    logger.info("delete_user user=%s counts=%s", user_id, counts)
    return counts


def export_user_data(user_id: str, db: Session) -> dict[str, Any]:
    def _rows(model):
        out = []
        for row in db.query(model).filter(model.user_id == user_id).all():
            item = {}
            for col in row.__table__.columns:
                val = getattr(row, col.name)
                if isinstance(val, datetime):
                    val = val.isoformat()
                item[col.name] = val
            out.append(item)
        return out

    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "engrams": _rows(Engram),
        "engram_links": _rows(EngramLink),
        "working_state": _rows(WorkingState),
        "self_traits": _rows(SelfTrait),
        "traces": _rows(Trace),
        "conversation_turns": _rows(ConversationTurn),
        "conversation_turn_engrams": _rows(ConversationTurnEngram),
    }


def prune_inspector_logs(db: Session, ttl_days: int) -> int:
    if ttl_days <= 0:
        return 0
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    old_ids = [
        r.id
        for r in db.query(LLMInteraction.id).filter(LLMInteraction.created_at < cutoff).all()
    ]
    if not old_ids:
        return 0
    db.query(LLMCallLog).filter(LLMCallLog.interaction_id.in_(old_ids)).delete(synchronize_session=False)
    n = db.query(LLMInteraction).filter(LLMInteraction.id.in_(old_ids)).delete(synchronize_session=False)
    db.commit()
    return n

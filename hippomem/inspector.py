"""
Inspector — DB query layer for LLM call traces and dashboard stats.
"""
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from hippomem.models.llm_interaction import LLMInteraction, LLMCallLog


def _interaction_summary(r: LLMInteraction) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "operation": r.operation,
        "call_count": r.call_count,
        "total_input_tokens": r.total_input_tokens,
        "total_output_tokens": r.total_output_tokens,
        "total_tokens": r.total_input_tokens + r.total_output_tokens,
        "total_cost": r.total_cost,
        "total_latency_ms": r.total_latency_ms,
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "turn_id": r.turn_id or "",
        "session_id": r.session_id or "",
    }


def _call_log_detail(c: LLMCallLog) -> dict:
    return {
        "step_order": c.step_order,
        "op": c.op,
        "model": c.model,
        "messages": c.messages or [],
        "raw_response": c.raw_response or "",
        "input_tokens": c.input_tokens,
        "output_tokens": c.output_tokens,
        "cost": c.cost,
        "latency_ms": c.latency_ms,
    }


def list_interactions(user_id: str, db: Session, limit: int = 50) -> list[dict]:
    """
    Return summary rows newest-first. No call logs loaded.
    """
    rows = (
        db.query(LLMInteraction)
        .filter(LLMInteraction.user_id == user_id)
        .order_by(LLMInteraction.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_interaction_summary(r) for r in rows]


def get_interaction_detail(
    interaction_id: str, db: Session
) -> Optional[dict]:
    """
    Return interaction header + ordered call logs (prompts + responses).
    """
    interaction = db.query(LLMInteraction).filter_by(id=interaction_id).first()
    if not interaction:
        return None
    calls = (
        db.query(LLMCallLog)
        .filter_by(interaction_id=interaction_id)
        .order_by(LLMCallLog.step_order)
        .all()
    )
    return {
        **_interaction_summary(interaction),
        "steps": [_call_log_detail(c) for c in calls],
    }


def get_by_turn_id(turn_id: str, db: Session) -> Optional[dict]:
    """
    Return all interaction rows sharing a turn_id (decode + encode pair).
    """
    rows = (
        db.query(LLMInteraction)
        .filter(LLMInteraction.turn_id == turn_id)
        .order_by(LLMInteraction.created_at)
        .all()
    )
    if not rows:
        return None
    interactions = []
    for row in rows:
        calls = (
            db.query(LLMCallLog)
            .filter_by(interaction_id=row.id)
            .order_by(LLMCallLog.step_order)
            .all()
        )
        interactions.append({
            **_interaction_summary(row),
            "output": row.output,
            "steps": [_call_log_detail(c) for c in calls],
        })
    return {"turn_id": turn_id, "interactions": interactions}


def get_stats(user_id: str, db: Session) -> dict:
    """
    Memory counts + aggregate usage stats for the dashboard.
    """
    from hippomem.models.engram import Engram, EngramKind
    from hippomem.models.working_state import WorkingState

    engram_counts = (
        db.query(Engram.engram_kind, func.count(Engram.id))
        .filter(Engram.user_id == user_id)
        .group_by(Engram.engram_kind)
        .all()
    )
    counts_by_kind = {k: v for k, v in engram_counts}

    # Active/dormant from WorkingState (global scope)
    ws = db.query(WorkingState).filter_by(
        user_id=user_id, session_id=None
    ).first()
    active_count = dormant_count = 0
    if ws and ws.state_data:
        active_count = len(ws.state_data.active_event_uuids or [])
        dormant_count = len(ws.state_data.recent_dormant_uuids or [])

    # Usage aggregates
    usage_agg = (
        db.query(
            func.count(LLMInteraction.id),
            func.sum(LLMInteraction.total_input_tokens),
            func.sum(LLMInteraction.total_output_tokens),
            func.sum(LLMInteraction.total_cost),
        )
        .filter(LLMInteraction.user_id == user_id)
        .first()
    )
    interaction_count, total_in, total_out, total_cost = usage_agg or (
        0,
        0,
        0,
        0.0,
    )

    return {
        "memory": {
            "total_engrams": sum(counts_by_kind.values()),
            "episodes": counts_by_kind.get(EngramKind.EPISODE.value, 0),
            "summaries": counts_by_kind.get(EngramKind.SUMMARY.value, 0),
            "entities": counts_by_kind.get(EngramKind.ENTITY.value, 0),
            "personas": counts_by_kind.get(EngramKind.PERSONA.value, 0),
            "active": active_count,
            "dormant": dormant_count,
        },
        "usage": {
            "total_interactions": interaction_count or 0,
            "total_input_tokens": total_in or 0,
            "total_output_tokens": total_out or 0,
            "total_tokens": (total_in or 0) + (total_out or 0),
            "total_cost": round(total_cost or 0.0, 6),
        },
    }

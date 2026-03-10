"""
Memory explorer queries — read-only DB queries for the memory graph UI.

Functions here are called by MemoryService thin wrappers (which own the DB session
lifecycle) and by the FastAPI memory explorer endpoints.
"""
from collections import defaultdict
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from hippomem.models.engram import Engram
from hippomem.models.engram_link import EngramLink
from hippomem.models.self_trait import SelfTrait
from hippomem.models.working_state import WorkingState


def get_graph_for_explorer(user_id: str, db: Session) -> Dict[str, Any]:
    """Return all nodes and edges for the memory explorer graph."""
    working_state = WorkingState.load(db, user_id, session_id=None)
    active_uuids = set(working_state.active_event_uuids) if working_state else set()
    dormant_uuids = set(working_state.recent_dormant_uuids) if working_state else set()

    rows = db.query(Engram).filter(Engram.user_id == user_id).all()
    nodes = []
    for row in rows:
        nodes.append({
            "id": row.engram_id,
            "core_intent": row.core_intent or "",
            "event_kind": row.engram_kind or "episode",
            "relevance_score": float(row.relevance_score or 1.0),
            "is_active": row.engram_id in active_uuids,
            "is_dormant": row.engram_id in dormant_uuids,
            "reinforcement_count": row.reinforcement_count or 0,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        })

    edge_rows = db.query(EngramLink).filter(EngramLink.user_id == user_id).all()
    edges = []
    for e in edge_rows:
        weight = float(e.weight or 0)
        # Mention links are created without weight; give them a visible default for the graph
        if e.link_kind == "mention" and weight == 0:
            weight = 0.25
        edges.append({
            "source": e.source_id,
            "target": e.target_id,
            "weight": weight,
            "link_kind": e.link_kind or "similarity",
        })

    return {"nodes": nodes, "edges": edges}


def get_event_detail_for_explorer(
    user_id: str, event_uuid: str, db: Session
) -> Optional[Dict[str, Any]]:
    """Return full event detail for the memory explorer."""
    working_state = WorkingState.load(db, user_id, session_id=None)
    active_uuids = set(working_state.active_event_uuids) if working_state else set()
    dormant_uuids = set(working_state.recent_dormant_uuids) if working_state else set()

    row = (
        db.query(Engram)
        .filter(
            Engram.user_id == user_id,
            Engram.engram_id == event_uuid,
        )
        .first()
    )
    if not row:
        return None

    outgoing = (
        db.query(EngramLink)
        .filter(
            EngramLink.user_id == user_id,
            EngramLink.source_id == event_uuid,
            EngramLink.link_kind != "mention",
        )
        .all()
    )
    incoming = (
        db.query(EngramLink)
        .filter(
            EngramLink.user_id == user_id,
            EngramLink.target_id == event_uuid,
            EngramLink.link_kind != "mention",
        )
        .all()
    )
    merged: dict[str, float] = defaultdict(float)
    for e in outgoing:
        merged[e.target_id] += float(e.weight or 0)
    for e in incoming:
        merged[e.source_id] += float(e.weight or 0)
    neighbor_edges = sorted(
        [{"neighbor_id": nid, "weight": w} for nid, w in merged.items()],
        key=lambda x: x["weight"],
        reverse=True,
    )

    return {
        "id": row.engram_id,
        "core_intent": row.core_intent or "",
        "event_kind": row.engram_kind or "episode",
        "updates": list(row.updates or []),
        "summary_text": row.summary_text,
        "relevance_score": float(row.relevance_score or 1.0),
        "reinforcement_count": row.reinforcement_count or 0,
        "is_active": row.engram_id in active_uuids,
        "is_dormant": row.engram_id in dormant_uuids,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "last_updated_at": (
            row.last_updated_at.isoformat() if row.last_updated_at else ""
        ),
        "edges": neighbor_edges,
    }


def get_entities_for_explorer(user_id: str, db: Session) -> Dict[str, Any]:
    """Return all ENTITY engrams for the persona explorer view."""
    rows = (
        db.query(Engram)
        .filter(Engram.user_id == user_id, Engram.engram_kind == "entity")
        .order_by(Engram.reinforcement_count.desc())
        .all()
    )
    entities = []
    for row in rows:
        entities.append({
            "id": row.engram_id,
            "canonical_name": row.core_intent or "",
            "entity_type": row.entity_type or "other",
            "facts": list(row.updates or []),
            "summary_text": row.summary_text,
            "reinforcement_count": row.reinforcement_count or 0,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        })
    return {"entities": entities}


def get_self_traits_for_explorer(user_id: str, db: Session) -> Dict[str, Any]:
    """Return all self traits for the self memory explorer view."""
    rows = db.query(SelfTrait).filter(SelfTrait.user_id == user_id).all()
    traits = []
    for row in rows:
        traits.append({
            "category": row.category,
            "key": row.key,
            "value": row.value,
            "previous_value": row.previous_value,
            "confidence_score": float(row.confidence_score or 0.0),
            "evidence_count": row.evidence_count or 0,
            "is_active": row.is_active,
            "first_observed_at": row.first_observed_at.isoformat() if row.first_observed_at else "",
            "last_observed_at": row.last_observed_at.isoformat() if row.last_observed_at else "",
        })
    return {"traits": traits}

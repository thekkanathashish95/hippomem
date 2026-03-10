"""
Engram link creation and strengthening.
"""
import logging
from datetime import datetime, timezone
from typing import List
from sqlalchemy.orm import Session

from hippomem.models.engram_link import EngramLink, LinkKind
from hippomem.config import (
    DEFAULT_EDGE_RETRIEVAL_BONUS as RETRIEVAL_BONUS,
    DEFAULT_EDGE_TEMPORAL_BONUS as TEMPORAL_BONUS,
)

logger = logging.getLogger(__name__)


def upsert_link(
    user_id: str,
    source_id: str,
    target_id: str,
    link_kind: LinkKind,
    delta: float,
    db: Session,
) -> None:
    """Create or update link. Normalizes (source, target) to canonical order."""
    a, b = sorted([source_id, target_id])
    logger.debug("upsert_link: %s→%s kind=%s weight=%.3f", a, b, link_kind.value, delta)
    link = db.query(EngramLink).filter(
        EngramLink.user_id == user_id,
        EngramLink.source_id == a,
        EngramLink.target_id == b,
        EngramLink.link_kind == link_kind.value,
    ).first()
    if link:
        link.weight = (link.weight or 0) + delta
        link.last_updated = datetime.now(timezone.utc)
    else:
        db.add(EngramLink(
            user_id=user_id,
            source_id=a,
            target_id=b,
            link_kind=link_kind.value,
            weight=delta,
        ))
    db.flush()


def strengthen_temporal_links(
    user_id: str,
    source_engram_ids: List[str],
    new_engram_id: str,
    db: Session,
) -> None:
    """
    Strengthen links between old engrams and a new engram.
    Called on create_new_branch to capture temporal succession.
    """
    logger.debug("temporal_links: %s → new=%s count=%d", [s[:8] for s in source_engram_ids], new_engram_id[:8], len(source_engram_ids))
    for old_id in source_engram_ids:
        upsert_link(user_id, old_id, new_engram_id, LinkKind.TEMPORAL, TEMPORAL_BONUS, db)


def strengthen_retrieval_links(
    user_id: str,
    used_engram_ids: List[str],
    db: Session,
) -> None:
    """
    Create or strengthen links between engrams used together in synthesis.
    Called when 2+ engrams are used in a single turn.
    """
    if len(used_engram_ids) < 2:
        return
    pairs = [(used_engram_ids[i], used_engram_ids[j]) for i in range(len(used_engram_ids)) for j in range(i + 1, len(used_engram_ids))]
    logger.debug("retrieval_links: strengthening %d pair(s) among engrams %s", len(pairs), [e[:8] for e in used_engram_ids])
    for a, b in pairs:
        upsert_link(user_id, a, b, LinkKind.RETRIEVAL, RETRIEVAL_BONUS, db)


def link_exists(user_id: str, a: str, b: str, link_kind: LinkKind, db: Session) -> bool:
    x, y = sorted([a, b])
    return db.query(EngramLink).filter(
        EngramLink.user_id == user_id,
        EngramLink.source_id == x,
        EngramLink.target_id == y,
        EngramLink.link_kind == link_kind.value,
    ).first() is not None

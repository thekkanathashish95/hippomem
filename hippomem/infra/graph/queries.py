"""
Graph traversal functions for engram graph (EngramLink).
Used by C3 long-term retrieval for graph expansion.
Excludes MENTION links from navigation — only traverse navigational links.
"""
from typing import Dict, List, Set, Tuple
from collections import deque
from sqlalchemy.orm import Session

from hippomem.models.engram_link import EngramLink, LinkKind


def get_neighbors(
    user_id: str,
    engram_id: str,
    db: Session,
    min_weight: float = 0.0,
) -> List[Tuple[str, float]]:
    """Get all engrams connected to the given engram (outgoing + incoming). Excludes MENTION links."""
    query_filter = [
        EngramLink.user_id == user_id,
        EngramLink.link_kind != LinkKind.MENTION.value,
        EngramLink.weight >= min_weight,
    ]
    outgoing = db.query(EngramLink).filter(
        *query_filter,
        EngramLink.source_id == engram_id,
    ).all()
    incoming = db.query(EngramLink).filter(
        *query_filter,
        EngramLink.target_id == engram_id,
    ).all()

    neighbors = []
    for link in outgoing:
        neighbors.append((link.target_id, float(link.weight or 0)))
    for link in incoming:
        neighbors.append((link.source_id, float(link.weight or 0)))
    return neighbors


def bfs_reachable(
    user_id: str,
    start_id: str,
    db: Session,
    max_depth: int = 2,
    min_weight: float = 0.1,
) -> Dict[str, int]:
    """Find all engrams reachable within N hops. Returns {engram_id: min_distance}."""
    visited: Dict[str, int] = {start_id: 0}
    queue: deque = deque([(start_id, 0)])

    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor_id, _ in get_neighbors(user_id, current, db, min_weight):
            if neighbor_id not in visited:
                visited[neighbor_id] = depth + 1
                queue.append((neighbor_id, depth + 1))

    return visited


def get_engram_cluster(
    user_id: str,
    seed_ids: List[str],
    db: Session,
    min_weight: float = 0.1,
) -> Set[str]:
    """Get all engrams in the same cluster as seed engrams (BFS from all seeds)."""
    cluster: Set[str] = set(seed_ids)
    queue: deque = deque(seed_ids)

    while queue:
        current = queue.popleft()
        for neighbor_id, _ in get_neighbors(user_id, current, db, min_weight):
            if neighbor_id not in cluster:
                cluster.add(neighbor_id)
                queue.append(neighbor_id)

    return cluster

"""
Test: get_neighbors returns empty list for isolated engram
Test: get_neighbors returns direct neighbors with weights
Test: get_neighbors includes both incoming and outgoing links
Test: min_weight filter excludes weak links
Test: bfs_reachable with max_depth=1 only returns direct neighbors
Test: bfs_reachable with max_depth=2 returns neighbors-of-neighbors
Test: get_engram_cluster returns connected component from seed
Test: disconnected engrams are NOT included in cluster
"""
from hippomem.models.engram_link import LinkKind
from hippomem.infra.graph.edges import upsert_link
from hippomem.infra.graph.queries import get_neighbors, bfs_reachable, get_engram_cluster


def test_get_neighbors_empty_for_isolated(db):
    neighbors = get_neighbors("user1", "isolated", db)
    assert neighbors == []


def test_get_neighbors_returns_direct_neighbors(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "event1", "event3", LinkKind.SIMILARITY, 0.3, db)

    neighbors = get_neighbors("user1", "event1", db)
    assert len(neighbors) == 2
    # Should include both outgoing edges
    neighbor_uuids = [uuid for uuid, weight in neighbors]
    assert "event2" in neighbor_uuids
    assert "event3" in neighbor_uuids


def test_get_neighbors_includes_incoming_and_outgoing(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "event3", "event1", LinkKind.SIMILARITY, 0.4, db)

    neighbors = get_neighbors("user1", "event1", db)
    neighbor_uuids = [uuid for uuid, weight in neighbors]
    assert "event2" in neighbor_uuids  # outgoing
    assert "event3" in neighbor_uuids  # incoming


def test_min_weight_filter_excludes_weak(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "event1", "event3", LinkKind.SIMILARITY, 0.1, db)

    neighbors = get_neighbors("user1", "event1", db, min_weight=0.3)
    neighbor_uuids = [uuid for uuid, weight in neighbors]
    assert "event2" in neighbor_uuids
    assert "event3" not in neighbor_uuids  # below threshold


def test_bfs_reachable_max_depth_1(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "event2", "event3", LinkKind.SIMILARITY, 0.5, db)

    reachable = bfs_reachable("user1", "event1", db, max_depth=1)
    assert "event1" in reachable
    assert "event2" in reachable
    assert "event3" not in reachable  # depth 2


def test_bfs_reachable_max_depth_2(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "event2", "event3", LinkKind.SIMILARITY, 0.5, db)

    reachable = bfs_reachable("user1", "event1", db, max_depth=2)
    assert "event1" in reachable
    assert "event2" in reachable
    assert "event3" in reachable


def test_get_engram_cluster_from_seed(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "event2", "event3", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "isolated", "isolated2", LinkKind.SIMILARITY, 0.5, db)

    cluster = get_engram_cluster("user1", ["event1"], db)
    assert "event1" in cluster
    assert "event2" in cluster
    assert "event3" in cluster
    assert "isolated" not in cluster
    assert "isolated2" not in cluster


def test_disconnected_engrams_not_in_cluster(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    upsert_link("user1", "event3", "event4", LinkKind.SIMILARITY, 0.5, db)

    cluster = get_engram_cluster("user1", ["event1"], db)
    assert "event1" in cluster
    assert "event2" in cluster
    assert "event3" not in cluster
    assert "event4" not in cluster

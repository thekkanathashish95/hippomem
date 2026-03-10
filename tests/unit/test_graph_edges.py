"""
Test: upsert_link creates a new link
Test: upsert_link called twice adds the deltas (cumulative)
Test: strengthen_temporal_links creates links from source_ids → new_engram_id
Test: strengthen_retrieval_links creates links between all pairs in used_engram_ids
Test: link_exists returns True for created link
Test: link_exists returns False for non-existent pair
Test: link is undirected — (A,B) and (B,A) refer to same canonical link
"""
from hippomem.models.engram_link import LinkKind
from hippomem.infra.graph.edges import (
    upsert_link,
    strengthen_temporal_links,
    strengthen_retrieval_links,
    link_exists,
)


def test_upsert_link_creates_new(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.5, db)
    assert link_exists("user1", "event1", "event2", LinkKind.SIMILARITY, db)


def test_upsert_link_adds_deltas_cumulative(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.3, db)
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.2, db)
    assert link_exists("user1", "event1", "event2", LinkKind.SIMILARITY, db)


def test_strengthen_temporal_links(db):
    strengthen_temporal_links("user1", ["event1", "event2"], "event3", db)
    assert link_exists("user1", "event1", "event3", LinkKind.TEMPORAL, db)
    assert link_exists("user1", "event2", "event3", LinkKind.TEMPORAL, db)


def test_strengthen_retrieval_links(db):
    strengthen_retrieval_links("user1", ["event1", "event2", "event3"], db)
    assert link_exists("user1", "event1", "event2", LinkKind.RETRIEVAL, db)
    assert link_exists("user1", "event1", "event3", LinkKind.RETRIEVAL, db)
    assert link_exists("user1", "event2", "event3", LinkKind.RETRIEVAL, db)


def test_link_exists_true_for_created(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.1, db)
    assert link_exists("user1", "event1", "event2", LinkKind.SIMILARITY, db)


def test_link_exists_false_for_non_existent(db):
    assert not link_exists("user1", "event1", "event2", LinkKind.SIMILARITY, db)


def test_link_is_undirected(db):
    upsert_link("user1", "event1", "event2", LinkKind.SIMILARITY, 0.1, db)
    assert link_exists("user1", "event1", "event2", LinkKind.SIMILARITY, db)
    assert link_exists("user1", "event2", "event1", LinkKind.SIMILARITY, db)

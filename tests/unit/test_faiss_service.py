"""
Test: get_or_create_index creates new index if none exists
Test: add_vector then search returns that vector's event_uuid
Test: search(k=2) on index with 1 vector returns 1 result
Test: remove_vector then search returns empty
Test: get_vector returns original vector (within float tolerance)
Test: exclude_event_uuid in search excludes that uuid from results
Test: save_index + load_index round-trip preserves vectors
Test: build_id_to_uuid_map returns correct mapping from DB
"""
import pytest
from unittest.mock import patch
from hippomem.infra.vector.faiss_service import FAISSService
from hippomem.models.engram import Engram


@pytest.fixture
def faiss_svc_4d(vector_dir):
    # Patch EMBEDDING_DIM to 4 so index creation matches our 4-dim test vectors
    with patch("hippomem.infra.vector.faiss_service.EMBEDDING_DIM", 4):
        svc = FAISSService(base_dir=vector_dir)
        yield svc


def test_get_or_create_index_creates_new(faiss_svc_4d):
    index = faiss_svc_4d.get_or_create_index("user1")
    assert index is not None
    assert index.ntotal == 0


def test_add_vector_then_search(faiss_svc_4d, db):
    # Create engram in DB
    event = Engram(
        engram_id="test-uuid",
        user_id="user1",
        core_intent="test intent",
        relevance_score=1.0,
    )
    db.add(event)
    db.commit()

    index = faiss_svc_4d.get_or_create_index("user1")
    faiss_svc_4d.add_vector("test-uuid", [0.1, 0.2, 0.3, 0.4], index)

    results = faiss_svc_4d.search([0.1, 0.2, 0.3, 0.4], 1, index)
    assert len(results) == 1
    faiss_id, similarity = results[0]
    # Check that we can map back to uuid
    id_map = faiss_svc_4d.build_id_to_uuid_map("user1", db)
    assert id_map[faiss_id] == "test-uuid"


def test_search_k2_on_index_with_1_vector(faiss_svc_4d):
    index = faiss_svc_4d.get_or_create_index("user1")
    faiss_svc_4d.add_vector("uuid1", [0.1, 0.2, 0.3, 0.4], index)

    results = faiss_svc_4d.search([0.1, 0.2, 0.3, 0.4], 2, index)
    assert len(results) == 1


def test_remove_vector_then_search_empty(faiss_svc_4d):
    index = faiss_svc_4d.get_or_create_index("user1")
    faiss_svc_4d.add_vector("uuid1", [0.1, 0.2, 0.3, 0.4], index)
    assert index.ntotal == 1

    faiss_svc_4d.remove_vector("uuid1", index)
    results = faiss_svc_4d.search([0.1, 0.2, 0.3, 0.4], 1, index)
    assert len(results) == 0


def test_get_vector_returns_original(faiss_svc_4d):
    import numpy as np
    index = faiss_svc_4d.get_or_create_index("user1")
    original = [0.1, 0.2, 0.3, 0.4]
    faiss_svc_4d.add_vector("uuid1", original, index)

    retrieved = faiss_svc_4d.get_vector("uuid1", index)
    assert retrieved is not None
    # FAISSService L2-normalizes before storing; compare direction (cosine similarity ≈ 1)
    orig_np = np.array(original, dtype=np.float32)
    orig_norm = orig_np / np.linalg.norm(orig_np)
    for a, b in zip(orig_norm.tolist(), retrieved):
        assert abs(a - b) < 1e-5


def test_exclude_event_uuid_in_search(faiss_svc_4d):
    index = faiss_svc_4d.get_or_create_index("user1")
    faiss_svc_4d.add_vector("uuid1", [0.1, 0.2, 0.3, 0.4], index)
    faiss_svc_4d.add_vector("uuid2", [0.1, 0.2, 0.3, 0.4], index)

    results = faiss_svc_4d.search([0.1, 0.2, 0.3, 0.4], 2, index, exclude_event_uuid="uuid1")
    assert len(results) == 1  # should exclude uuid1


def test_save_load_index_round_trip(faiss_svc_4d):
    index = faiss_svc_4d.get_or_create_index("user1")
    faiss_svc_4d.add_vector("uuid1", [0.1, 0.2, 0.3, 0.4], index)
    faiss_svc_4d.save_index("user1", index)

    loaded = faiss_svc_4d.load_index("user1")
    assert loaded is not None
    assert loaded.ntotal == 1


def test_build_id_to_uuid_map(faiss_svc_4d, db):
    # Create engrams
    event1 = Engram(engram_id="uuid1", user_id="user1", core_intent="intent1", relevance_score=1.0)
    event2 = Engram(engram_id="uuid2", user_id="user1", core_intent="intent2", relevance_score=1.0)
    db.add(event1)
    db.add(event2)
    db.commit()

    id_map = faiss_svc_4d.build_id_to_uuid_map("user1", db)
    assert len(id_map) == 2
    assert "uuid1" in id_map.values()
    assert "uuid2" in id_map.values()

"""
Unit tests for LongTermRetriever.retrieve() from decoder/long_term.py.
"""
from unittest.mock import MagicMock

from hippomem.decoder.long_term import LongTermRetriever
from hippomem.models.engram import Engram
from hippomem.models.engram_link import EngramLink, LinkKind


def test_retrieve_empty_index_returns_empty(db, mock_embeddings, faiss_svc):
    """No FAISS results → LongTermResult(events=[], total_found=0)."""
    retriever = LongTermRetriever(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    result = retriever.retrieve(
        query="test",
        conversation_window="",
        exclude_uuids=[],
        user_id="user1",
        db=db,
    )
    assert result.events == []
    assert result.total_found == 0
    assert result.graph_expanded == []


def test_retrieve_excludes_active_and_dormant_uuids(db, mock_embeddings, faiss_svc):
    """FAISS returns UUID in exclude list → not included in events."""
    for i in range(2):
        e = Engram(
            user_id="user1",
            engram_id=f"ev{i}",
            core_intent=f"intent{i}",
            relevance_score=1.0,
        )
        db.add(e)
    db.commit()

    index = faiss_svc.get_or_create_index("user1")
    vec = mock_embeddings.embed("test")
    faiss_svc.add_vector("ev0", vec, index)
    faiss_svc.add_vector("ev1", vec, index)
    faiss_svc.save_index("user1", index)

    retriever = LongTermRetriever(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    result = retriever.retrieve(
        query="test",
        conversation_window="",
        exclude_uuids=["ev0"],
        user_id="user1",
        db=db,
        top_k=5,
    )
    uuids = [e["event_uuid"] for e in result.events]
    assert "ev0" not in uuids
    assert "ev1" in uuids


def test_retrieve_graph_expansion_disabled(db, mock_embeddings, faiss_svc):
    """enable_graph_expansion=False → no neighbor lookup."""
    e = Engram(
        user_id="user1",
        engram_id="ev1",
        core_intent="intent1",
        relevance_score=1.0,
    )
    db.add(e)
    db.commit()

    index = faiss_svc.get_or_create_index("user1")
    vec = mock_embeddings.embed("test")
    faiss_svc.add_vector("ev1", vec, index)
    faiss_svc.save_index("user1", index)

    retriever = LongTermRetriever(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    result = retriever.retrieve(
        query="test",
        conversation_window="",
        exclude_uuids=[],
        user_id="user1",
        db=db,
        enable_graph_expansion=False,
    )
    assert len(result.events) == 1
    assert result.events[0]["source"] == "faiss"
    assert result.graph_expanded == []


def test_retrieve_graph_expansion_adds_neighbors(db, mock_embeddings, faiss_svc):
    """Neighbor UUID not in FAISS results → added to graph_expanded."""
    e1 = Engram(
        user_id="user1",
        engram_id="ev1",
        core_intent="intent1",
        relevance_score=1.0,
    )
    e2 = Engram(
        user_id="user1",
        engram_id="ev2",
        core_intent="intent2",
        relevance_score=1.0,
    )
    db.add_all([e1, e2])
    db.commit()

    link = EngramLink(
        user_id="user1",
        source_id="ev1",
        target_id="ev2",
        link_kind=LinkKind.TEMPORAL.value,
        weight=0.5,
    )
    db.add(link)
    db.commit()

    index = faiss_svc.get_or_create_index("user1")
    vec = mock_embeddings.embed("test")
    faiss_svc.add_vector("ev1", vec, index)
    faiss_svc.save_index("user1", index)

    retriever = LongTermRetriever(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    result = retriever.retrieve(
        query="test",
        conversation_window="",
        exclude_uuids=[],
        user_id="user1",
        db=db,
        enable_graph_expansion=True,
        max_graph_events=5,
    )
    assert len(result.events) >= 1
    graph_uuids = [e["event_uuid"] for e in result.graph_expanded]
    assert "ev2" in graph_uuids
    assert any(e["source"] == "graph" for e in result.events)


def test_retrieve_embedding_failure_returns_empty(db, faiss_svc):
    """embed() raises → empty result."""
    mock_emb = MagicMock()
    mock_emb.embed.side_effect = Exception("embed failed")

    retriever = LongTermRetriever(
        embedding_service=mock_emb,
        faiss_service=faiss_svc,
    )
    result = retriever.retrieve(
        query="test",
        conversation_window="",
        exclude_uuids=[],
        user_id="user1",
        db=db,
    )
    assert result.events == []
    assert result.total_found == 0

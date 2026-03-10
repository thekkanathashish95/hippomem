"""
Unit tests for RetrieveService — mode-driven retrieval.
"""
import pytest

from hippomem.models.engram import Engram, EngramKind
from hippomem.retrieve.service import RetrieveService
from hippomem.retrieve.schemas import RetrieveResult, RetrievedEpisode


def test_retrieve_empty_faiss_returns_empty(db, mock_embeddings, vector_dir):
    """No FAISS index → empty RetrieveResult."""
    from hippomem.config import MemoryConfig

    config = MemoryConfig(vector_dir=vector_dir)
    svc = RetrieveService(embedding_service=mock_embeddings, config=config)
    result = svc.retrieve(
        user_id="user1",
        query="test",
        db=db,
        mode="faiss",
        top_k=5,
    )
    assert isinstance(result, RetrieveResult)
    assert result.episodes == []
    assert result.total_primary == 0


def test_retrieve_bm25_empty_returns_empty(db, mock_embeddings, vector_dir):
    """BM25 mode with no episodic engrams → empty."""
    from hippomem.config import MemoryConfig

    config = MemoryConfig(vector_dir=vector_dir)
    svc = RetrieveService(embedding_service=mock_embeddings, config=config)
    result = svc.retrieve(
        user_id="user1",
        query="test",
        db=db,
        mode="bm25",
        top_k=5,
    )
    assert result.episodes == []
    assert result.total_primary == 0


def test_retrieve_faiss_returns_episodes(db, mock_embeddings, faiss_svc, vector_dir):
    """FAISS mode with index → returns RetrievedEpisodes."""
    from hippomem.config import MemoryConfig

    e = Engram(
        user_id="user1",
        engram_id="ev1",
        core_intent="User was debugging Python",
        engram_kind=EngramKind.EPISODE.value,
        relevance_score=1.0,
    )
    db.add(e)
    db.commit()

    index = faiss_svc.get_or_create_index("user1")
    vec = mock_embeddings.embed("test")
    faiss_svc.add_vector("ev1", vec, index)
    faiss_svc.save_index("user1", index)

    config = MemoryConfig(vector_dir=vector_dir)
    svc = RetrieveService(embedding_service=mock_embeddings, config=config)
    result = svc.retrieve(
        user_id="user1",
        query="Python debugging",
        db=db,
        mode="faiss",
        top_k=5,
    )
    assert result.total_primary == 1
    assert len(result.episodes) == 1
    ep = result.episodes[0]
    assert isinstance(ep, RetrievedEpisode)
    assert ep.event_uuid == "ev1"
    assert ep.core_intent == "User was debugging Python"
    assert ep.source == "faiss"
    assert ep.graph_hop == 0
    assert ep.entities == []
    assert ep.related_episodes == []


def test_retrieve_invalid_mode_raises(db, mock_embeddings, vector_dir):
    """Invalid mode raises ValueError."""
    from hippomem.config import MemoryConfig

    config = MemoryConfig(vector_dir=vector_dir)
    svc = RetrieveService(embedding_service=mock_embeddings, config=config)
    with pytest.raises(ValueError, match="mode must be"):
        svc.retrieve(
            user_id="user1",
            query="test",
            db=db,
            mode="invalid",
        )

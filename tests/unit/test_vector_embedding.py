"""
Unit tests for infra/vector/embedding.py.
"""
from unittest.mock import MagicMock

from hippomem.infra.vector.embedding import (
    compute_content_hash,
    embed_engram,
    add_to_faiss_realtime,
)
from hippomem.models.engram import Engram


def test_compute_content_hash_stable():
    """Same core_intent + updates → same hash on repeated calls."""
    h1 = compute_content_hash("intent", ["update1", "update2"])
    h2 = compute_content_hash("intent", ["update1", "update2"])
    assert h1 == h2


def test_compute_content_hash_different_content_different_hash():
    """Different inputs → different hash."""
    h1 = compute_content_hash("intent1", ["update1"])
    h2 = compute_content_hash("intent2", ["update1"])
    assert h1 != h2

    h3 = compute_content_hash("intent", ["update1"])
    h4 = compute_content_hash("intent", ["update2"])
    assert h3 != h4


def test_compute_content_hash_empty_updates():
    """Empty list handled without error."""
    h = compute_content_hash("intent", [])
    assert len(h) == 16
    assert isinstance(h, str)


def test_embed_engram_returns_vector_and_hash(mock_embeddings):
    """Mock embed returns vector → returns (vector, hash) tuple."""
    result = embed_engram(
        engram_id="e1",
        core_intent="test intent",
        updates=["update1"],
        embedding_svc=mock_embeddings,
    )
    assert result is not None
    vector, content_hash = result
    assert vector == [0.1] * 1536
    assert len(content_hash) == 16
    assert content_hash == compute_content_hash("test intent", ["update1"])


def test_embed_engram_returns_none_on_failure():
    """embed raises → returns None."""
    mock_emb = MagicMock()
    mock_emb.embed.side_effect = Exception("embed failed")

    result = embed_engram(
        engram_id="e1",
        core_intent="test",
        updates=[],
        embedding_svc=mock_emb,
    )
    assert result is None


def test_add_to_faiss_realtime_updates_content_hash(db, mock_embeddings, faiss_svc):
    """After call, Engram.content_hash updated in DB."""
    e = Engram(
        user_id="user1",
        engram_id="ev1",
        core_intent="intent",
        content_hash=None,
        relevance_score=1.0,
    )
    db.add(e)
    db.commit()

    index = faiss_svc.get_or_create_index("user1")
    vec = mock_embeddings.embed("test")
    content_hash = compute_content_hash("intent", ["update1"])

    add_to_faiss_realtime(
        user_id="user1",
        engram_id="ev1",
        vector=vec,
        content_hash=content_hash,
        faiss_svc=faiss_svc,
        index=index,
        db=db,
    )

    db.refresh(e)
    assert e.content_hash == content_hash

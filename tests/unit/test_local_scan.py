"""
Unit tests for LocalScanRanker.scan_and_rank() from decoder/local_scan.py.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

from hippomem.decoder.local_scan import LocalScanRanker
from hippomem.models.engram import Engram


def test_scan_empty_events_returns_empty_result(db, mock_embeddings, faiss_svc):
    """No active/dormant events → LocalScanResult.events=[], high_confidence=False."""
    ranker = LocalScanRanker(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    result = ranker.scan_and_rank(
        query="test",
        conversation_window="",
        active_events=[],
        dormant_events=[],
        user_id="user1",
        db=db,
    )
    assert result.events == []
    assert result.high_confidence is False


def test_scan_score_above_threshold_sets_high_confidence(db, mock_embeddings, faiss_svc):
    """Mock embedding returns high-similarity vector → high_confidence=True."""
    event = Engram(
        user_id="user1",
        engram_id="ev1",
        core_intent="test intent",
        relevance_score=1.0,
        last_updated_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()

    ranker = LocalScanRanker(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    result = ranker.scan_and_rank(
        query="test",
        conversation_window="",
        active_events=[{"event_uuid": "ev1", "core_intent": "test intent"}],
        dormant_events=[],
        user_id="user1",
        db=db,
    )
    assert len(result.events) >= 1
    assert result.high_confidence is True


def test_scan_score_below_threshold_low_confidence(db, faiss_svc):
    """Low similarity → high_confidence=False."""
    mock_emb = MagicMock()
    mock_emb.embed.return_value = [0.1] * 1536
    mock_emb.embed_batch.side_effect = Exception("batch fail")

    event = Engram(
        user_id="user1",
        engram_id="ev1",
        core_intent="test",
        relevance_score=0.5,
    )
    db.add(event)
    db.commit()

    ranker = LocalScanRanker(
        embedding_service=mock_emb,
        faiss_service=faiss_svc,
    )
    result = ranker.scan_and_rank(
        query="test",
        conversation_window="",
        active_events=[{"event_uuid": "ev1", "core_intent": "test"}],
        dormant_events=[],
        user_id="user1",
        db=db,
        threshold=0.6,
    )
    assert result.high_confidence is False


def test_scan_respects_top_active_limit(db, mock_embeddings, faiss_svc):
    """5 active events → returns only top 3."""
    for i in range(5):
        e = Engram(
            user_id="user1",
            engram_id=f"ev{i}",
            core_intent=f"intent{i}",
            relevance_score=1.0,
        )
        db.add(e)
    db.commit()

    ranker = LocalScanRanker(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    active = [{"event_uuid": f"ev{i}", "core_intent": f"intent{i}"} for i in range(5)]
    result = ranker.scan_and_rank(
        query="test",
        conversation_window="",
        active_events=active,
        dormant_events=[],
        user_id="user1",
        db=db,
        top_active=3,
        top_dormant=2,
    )
    assert len(result.events) == 3


def test_scan_ranks_by_combined_score(db, mock_embeddings, faiss_svc):
    """Events with different scores → highest-scoring first."""
    now = datetime.now(timezone.utc)
    vec = [0.1] * 1536
    mock_embeddings.embed_batch.return_value = [vec, vec, vec]

    for i, rel in enumerate([0.2, 1.0, 0.1]):
        e = Engram(
            user_id="user1",
            engram_id=f"ev{i}",
            core_intent=f"intent{i}",
            relevance_score=rel,
            last_updated_at=now,
        )
        db.add(e)
    db.commit()

    ranker = LocalScanRanker(
        embedding_service=mock_embeddings,
        faiss_service=faiss_svc,
    )
    active = [{"event_uuid": f"ev{i}", "core_intent": f"intent{i}"} for i in range(3)]
    result = ranker.scan_and_rank(
        query="test",
        conversation_window="",
        active_events=active,
        dormant_events=[],
        user_id="user1",
        db=db,
        top_active=3,
    )
    assert len(result.events) == 3
    assert result.events[0]["event_uuid"] == "ev1"


def test_scan_embedding_failure_returns_empty(db, faiss_svc):
    """embed() raises exception → empty result."""
    mock_emb = MagicMock()
    mock_emb.embed.side_effect = Exception("embed failed")

    ranker = LocalScanRanker(
        embedding_service=mock_emb,
        faiss_service=faiss_svc,
    )
    result = ranker.scan_and_rank(
        query="test",
        conversation_window="",
        active_events=[{"event_uuid": "ev1", "core_intent": "test"}],
        dormant_events=[],
        user_id="user1",
        db=db,
    )
    assert result.events == []
    assert result.high_confidence is False

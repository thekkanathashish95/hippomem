"""
Test: score_event() with all three weights
Test: recency weight is 0 when last_updated is None
Test: weights sum to 1.0 produces score in [0, 1]
Test: score_event_with_breakdown() returns correct keys in breakdown dict
Test: zero semantic similarity + high relevance → score < 0.5 (weight math)
"""
from datetime import datetime, timezone
from hippomem.decoder.scoring import score_event, score_engram_with_breakdown


def test_score_event_with_three_weights():
    semantic = 0.8
    relevance = 0.6
    last_updated = datetime.now(timezone.utc)
    score = score_event(semantic, relevance, last_updated)
    assert 0 <= score <= 1


def test_recency_weight_zero_when_none():
    semantic = 0.5
    relevance = 0.5
    score = score_event(semantic, relevance, None)
    # With recency=0, score should be 0.5*0.5 + 0.3*0.5 + 0.2*0 = 0.4
    expected = 0.5 * 0.5 + 0.3 * 0.5 + 0.2 * 0
    assert abs(score - expected) < 0.001


def test_weights_sum_to_one():
    semantic = 0.7
    relevance = 0.8
    last_updated = datetime.now(timezone.utc)
    score = score_event(semantic, relevance, last_updated)
    assert 0 <= score <= 1


def test_score_engram_with_breakdown_keys():
    semantic = 0.6
    relevance = 0.4
    last_updated = datetime.now(timezone.utc)
    score, breakdown = score_engram_with_breakdown(semantic, relevance, last_updated)
    assert "semantic" in breakdown
    assert "relevance" in breakdown
    assert "recency" in breakdown
    assert "combined" in breakdown
    assert abs(breakdown["combined"] - score) < 1e-10


def test_zero_semantic_high_relevance_score():
    from datetime import timedelta
    semantic = 0.0
    relevance = 1.0
    # Use a past timestamp so recency < 1 (recency = 1 at now() makes score exactly 0.5)
    last_updated = datetime.now(timezone.utc) - timedelta(hours=1)
    score = score_event(semantic, relevance, last_updated)
    # 0.5*0 + 0.3*1 + 0.2*recency < 0.5 since recency < 1
    assert score < 0.5

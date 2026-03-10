"""
Test: apply_decay reduces relevance_score by ~4% (2 hrs × 2%/hr)
Test: apply_decay doesn't go below 0
Test: apply_decay updates last_decay_applied_at timestamp
Test: apply_decay_uuids only affects specified uuids, not others
Test: consolidate() with stale event at capacity demotes it
Test: consolidate() with events below capacity does not demote even if stale
"""
from datetime import datetime, timezone, timedelta
from hippomem.consolidator.service import ConsolidationService, ConsolidationConfig
from hippomem.models.engram import Engram
from hippomem.schemas.working_state import WorkingStateData


def test_apply_decay_reduces_relevance_score(db, config):
    # Create event with relevance_score=1.0, last_decay_applied_at=2 hours ago
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    event = Engram(
        user_id="user1",
        engram_id="event1",
        relevance_score=1.0,
        last_decay_applied_at=two_hours_ago,
    )
    db.add(event)
    db.commit()

    service = ConsolidationService()
    service.apply_decay_uuids("user1", "session1", ["event1"], db)

    db.flush()
    db.refresh(event)
    # Should decay by ~4% (2 hrs × 2%/hr = ~4% loss)
    expected = 1.0 * (0.98 ** 2)  # ~0.9604
    assert abs(event.relevance_score - expected) < 0.01


def test_apply_decay_doesnt_go_below_zero(db):
    # Create event with very low score
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1000)
    event = Engram(
        user_id="user1",
        engram_id="event1",
        relevance_score=0.01,
        last_decay_applied_at=long_ago,
    )
    db.add(event)
    db.commit()

    service = ConsolidationService()
    service.apply_decay_uuids("user1", "session1", ["event1"], db)

    db.refresh(event)
    assert event.relevance_score >= 0


def test_apply_decay_updates_timestamp(db):
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    event = Engram(
        user_id="user1",
        engram_id="event1",
        relevance_score=1.0,
        last_decay_applied_at=two_hours_ago,
    )
    db.add(event)
    db.commit()

    service = ConsolidationService()
    service.apply_decay_uuids("user1", "session1", ["event1"], db)

    db.flush()
    db.refresh(event)
    # SQLite may return naive datetimes; normalize before comparing
    ts = event.last_decay_applied_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    assert ts > two_hours_ago


def test_apply_decay_uuids_only_affects_specified(db):
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)

    # Create two events
    event1 = Engram(
        user_id="user1",
        engram_id="event1",
        relevance_score=1.0,
        last_decay_applied_at=two_hours_ago,
    )
    event2 = Engram(
        user_id="user1",
        engram_id="event2",
        relevance_score=1.0,
        last_decay_applied_at=two_hours_ago,
    )
    db.add(event1)
    db.add(event2)
    db.commit()

    service = ConsolidationService()
    # Only decay event1
    service.apply_decay_uuids("user1", "session1", ["event1"], db)

    db.flush()
    db.refresh(event1)
    db.refresh(event2)

    # event1 should be decayed
    assert event1.relevance_score < 1.0
    # event2 should remain unchanged
    assert event2.relevance_score == 1.0


def test_consolidate_demotes_stale_event_at_capacity(db, config):
    """Staleness demotion: stale event (low relevance, old) at capacity is demoted."""
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)

    for i in range(3):
        relevance = 0.1 if i == 0 else 1.0  # event0 is stale candidate
        db.add(Engram(
            user_id="user1",
            engram_id=f"event{i}",
            relevance_score=relevance,
            last_decay_applied_at=two_hours_ago,
            last_updated_at=two_hours_ago,
        ))
    db.commit()

    working_state = WorkingStateData(
        working_state_id="test",
        last_updated=datetime.now(timezone.utc).isoformat(),
        active_event_uuids=["event0", "event1", "event2"],
        recent_dormant_uuids=[],
    )

    # stale_after_minutes=60: events touched 2h ago qualify as stale
    service = ConsolidationService(config=ConsolidationConfig(
        max_active_events=3, max_dormant_events=3, stale_after_minutes=60
    ))
    result = service.consolidate("user1", "session1", db, working_state)

    assert len(result.demoted_event_ids) == 1
    assert result.demoted_event_ids[0] == "event0"
    assert result.total_active_after == 2
    assert "event0" not in working_state.active_event_uuids
    assert "event0" in working_state.recent_dormant_uuids


def test_consolidate_no_demotion_below_capacity(db, config):
    """Staleness demotion: even stale events are not demoted when below capacity."""
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)

    for i in range(2):
        db.add(Engram(
            user_id="user1",
            engram_id=f"event{i}",
            relevance_score=0.1,  # stale relevance
            last_decay_applied_at=two_hours_ago,
            last_updated_at=two_hours_ago,
        ))
    db.commit()

    working_state = WorkingStateData(
        working_state_id="test",
        last_updated=datetime.now(timezone.utc).isoformat(),
        active_event_uuids=["event0", "event1"],
        recent_dormant_uuids=[],
    )

    # max_active_events=3, only 2 active → below capacity → no demotion
    service = ConsolidationService(config=ConsolidationConfig(
        max_active_events=3, max_dormant_events=3, stale_after_minutes=60
    ))
    result = service.consolidate("user1", "session1", db, working_state)

    assert len(result.demoted_event_ids) == 0
    assert result.total_active_after == 2

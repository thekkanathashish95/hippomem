"""
Test: apply_decay reduces relevance_score by ~4% (2 hrs × 2%/hr)
Test: apply_decay doesn't go below 0
Test: apply_decay updates last_decay_applied_at timestamp
Test: apply_decay_uuids only affects specified uuids, not others
Test: enrich_entity_profiles processes only engrams where needs_consolidation=True
Test: enrich_entity_profiles clears pending_facts and needs_consolidation after run
Test: enrich_entity_profiles skips engrams where needs_consolidation=False
Test: consolidate_episode_facts processes only episodes where needs_consolidation=True
Test: consolidate_episode_facts clears pending_facts and needs_consolidation after run
Test: consolidate_episode_facts skips engrams where needs_consolidation=False
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from hippomem.consolidator.service import (
    ConsolidationService,
    enrich_entity_profiles,
    consolidate_episode_facts,
)
from hippomem.models.engram import Engram, EngramKind


# ── Decay tests ───────────────────────────────────────────────────────────────

def test_apply_decay_reduces_relevance_score(db, config):
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
    expected = 1.0 * (0.98 ** 2)
    assert abs(event.relevance_score - expected) < 0.01


def test_apply_decay_doesnt_go_below_zero(db):
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
    ts = event.last_decay_applied_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    assert ts > two_hours_ago


def test_apply_decay_uuids_only_affects_specified(db):
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    event1 = Engram(
        user_id="user1", engram_id="event1",
        relevance_score=1.0, last_decay_applied_at=two_hours_ago,
    )
    event2 = Engram(
        user_id="user1", engram_id="event2",
        relevance_score=1.0, last_decay_applied_at=two_hours_ago,
    )
    db.add(event1)
    db.add(event2)
    db.commit()

    service = ConsolidationService()
    service.apply_decay_uuids("user1", "session1", ["event1"], db)

    db.flush()
    db.refresh(event1)
    db.refresh(event2)
    assert event1.relevance_score < 1.0
    assert event2.relevance_score == 1.0


# ── Entity enrichment tests ───────────────────────────────────────────────────

def _make_llm_ops_entity(merged_facts=None, summary_text="Test summary"):
    llm_ops = MagicMock()
    llm_ops.update_entity_profile.return_value = {
        "merged_facts": merged_facts or ["merged fact"],
        "summary_text": summary_text,
    }
    return llm_ops


def _make_embedding_service():
    svc = MagicMock()
    svc.embed.return_value = [0.1] * 256
    return svc


def test_enrich_entity_profiles_processes_flagged_rows(db, tmp_path):
    """enrich_entity_profiles runs LLM for rows with needs_consolidation=True."""
    entity = Engram(
        user_id="user1",
        engram_id="e1",
        engram_kind=EngramKind.ENTITY.value,
        core_intent="Alice",
        entity_type="person",
        updates=["works at Acme"],
        pending_facts=["promoted to VP"],
        needs_consolidation=True,
        relevance_score=1.0,
    )
    db.add(entity)
    db.commit()

    llm_ops = _make_llm_ops_entity(merged_facts=["works at Acme", "promoted to VP"])
    emb_svc = _make_embedding_service()

    enrich_entity_profiles("user1", db, llm_ops, emb_svc, str(tmp_path))

    db.refresh(entity)
    llm_ops.update_entity_profile.assert_called_once()
    call_kwargs = llm_ops.update_entity_profile.call_args.kwargs
    assert call_kwargs["consolidated_facts"] == ["works at Acme"]
    assert call_kwargs["pending_facts"] == ["promoted to VP"]


def test_enrich_entity_profiles_clears_pending_and_flag(db, tmp_path):
    """After enrichment, pending_facts is empty and needs_consolidation is False."""
    entity = Engram(
        user_id="user1",
        engram_id="e1",
        engram_kind=EngramKind.ENTITY.value,
        core_intent="Alice",
        entity_type="person",
        updates=[],
        pending_facts=["works at Acme"],
        needs_consolidation=True,
        relevance_score=1.0,
    )
    db.add(entity)
    db.commit()

    enrich_entity_profiles(
        "user1", db, _make_llm_ops_entity(), _make_embedding_service(), str(tmp_path)
    )

    db.refresh(entity)
    assert entity.pending_facts == [] or entity.pending_facts is None or entity.pending_facts == []
    assert entity.needs_consolidation is False


def test_enrich_entity_profiles_skips_unflagged_rows(db, tmp_path):
    """enrich_entity_profiles does not call LLM for rows with needs_consolidation=False."""
    entity = Engram(
        user_id="user1",
        engram_id="e1",
        engram_kind=EngramKind.ENTITY.value,
        core_intent="Alice",
        entity_type="person",
        updates=["works at Acme"],
        pending_facts=[],
        needs_consolidation=False,
        relevance_score=1.0,
    )
    db.add(entity)
    db.commit()

    llm_ops = _make_llm_ops_entity()
    enrich_entity_profiles("user1", db, llm_ops, _make_embedding_service(), str(tmp_path))

    llm_ops.update_entity_profile.assert_not_called()


# ── Episode consolidation tests ───────────────────────────────────────────────

def _make_llm_ops_episode(merged_updates=None):
    llm_ops = MagicMock()
    llm_ops.consolidate_episode_updates.return_value = {
        "merged_updates": merged_updates or ["merged update"],
    }
    return llm_ops


def test_consolidate_episode_facts_processes_flagged_rows(db, tmp_path):
    """consolidate_episode_facts runs LLM for episodes with needs_consolidation=True."""
    episode = Engram(
        user_id="user1",
        engram_id="ep1",
        engram_kind=EngramKind.EPISODE.value,
        core_intent="Planning hippomem architecture",
        updates=["Decided to use SQLite"],
        pending_facts=["Changed to support multiple backends"],
        needs_consolidation=True,
        relevance_score=1.0,
    )
    db.add(episode)
    db.commit()

    llm_ops = _make_llm_ops_episode(
        merged_updates=["Using SQLite with planned multi-backend support"]
    )
    emb_svc = _make_embedding_service()

    consolidate_episode_facts("user1", db, llm_ops, emb_svc, str(tmp_path))

    db.refresh(episode)
    llm_ops.consolidate_episode_updates.assert_called_once()
    call_kwargs = llm_ops.consolidate_episode_updates.call_args.kwargs
    assert call_kwargs["consolidated_updates"] == ["Decided to use SQLite"]
    assert call_kwargs["pending_updates"] == ["Changed to support multiple backends"]


def test_consolidate_episode_facts_clears_pending_and_flag(db, tmp_path):
    """After consolidation, pending_facts is empty and needs_consolidation is False."""
    episode = Engram(
        user_id="user1",
        engram_id="ep1",
        engram_kind=EngramKind.EPISODE.value,
        core_intent="Building hippomem",
        updates=[],
        pending_facts=["Started the project"],
        needs_consolidation=True,
        relevance_score=1.0,
    )
    db.add(episode)
    db.commit()

    consolidate_episode_facts(
        "user1", db, _make_llm_ops_episode(), _make_embedding_service(), str(tmp_path)
    )

    db.refresh(episode)
    assert episode.pending_facts == [] or episode.pending_facts is None or episode.pending_facts == []
    assert episode.needs_consolidation is False


def test_consolidate_episode_facts_skips_unflagged_rows(db, tmp_path):
    """consolidate_episode_facts does not call LLM for rows with needs_consolidation=False."""
    episode = Engram(
        user_id="user1",
        engram_id="ep1",
        engram_kind=EngramKind.EPISODE.value,
        core_intent="Building hippomem",
        updates=["Started the project"],
        pending_facts=[],
        needs_consolidation=False,
        relevance_score=1.0,
    )
    db.add(episode)
    db.commit()

    llm_ops = _make_llm_ops_episode()
    consolidate_episode_facts("user1", db, llm_ops, _make_embedding_service(), str(tmp_path))

    llm_ops.consolidate_episode_updates.assert_not_called()

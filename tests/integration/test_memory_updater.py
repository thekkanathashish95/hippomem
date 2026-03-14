"""
Test: update() calls EpisodicLLMOps.extract_event_update with the right events
Test: event.updates list is extended with the returned update string
Test: event.reinforcement_count increments
Test: decay is applied after update
Test: returned dict contains updated working_state

Test (Path B create): when LLM says should_create_new_event=True, creates Engram row
Test (Path B create): new event gets added to active_event_uuids
Test (Path B ETS): when LLM says should_create_new_event=False, calls maybe_append_to_ets
Test (Path B ETS): trace is appended to Trace table

Test: after creating a 4th event, one gets demoted to dormant
Test: demoted event uuid moves to recent_dormant_uuids in WorkingState
"""
from unittest.mock import MagicMock
from hippomem.encoder.updater import MemoryEncoder
from hippomem.memory.episodic.llm_ops import EpisodicLLMOps
from hippomem.models.engram import Engram
from hippomem.models.working_state import WorkingState
from hippomem.schemas.working_state import WorkingStateData
from hippomem.config import MemoryConfig


def test_update_calls_extract_event_update_with_right_events(db, mock_llm, mock_embeddings, config):
    # Create event in DB and working state
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["old update"],
        relevance_score=1.0,
    )
    db.add(event)
    db.commit()

    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )

    # Mock LLM ops
    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.detect_drift.return_value = ("update_existing", "no drift")
    llm_ops.extract_event_update.return_value = [{"add_update": True, "update": "new update"}]

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    updater.update("user1", "session1", conversation_history, db, used_engram_ids=["event1"])

    llm_ops.extract_event_update.assert_called_once()
    call_args = llm_ops.extract_event_update.call_args[0]
    events = call_args[0]
    assert len(events) == 1
    assert events[0]["event_uuid"] == "event1"


def test_event_updates_list_extended_with_returned_update(db, mock_llm, mock_embeddings, config):
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["old update"],
        relevance_score=1.0,
    )
    db.add(event)
    db.commit()

    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.detect_drift.return_value = ("update_existing", "no drift")
    llm_ops.extract_event_update.return_value = [{"add_update": True, "update": "new update"}]

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    updater.update("user1", "session1", conversation_history, db, used_engram_ids=["event1"])

    db.refresh(event)
    # old update stays in consolidated updates; new update goes to pending_facts until consolidation
    assert "old update" in event.updates
    assert "new update" in (event.pending_facts or [])


def test_event_reinforcement_count_increments(db, mock_llm, mock_embeddings, config):
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["old update"],
        relevance_score=1.0,
        reinforcement_count=2,
    )
    db.add(event)
    db.commit()

    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.detect_drift.return_value = ("update_existing", "no drift")
    llm_ops.extract_event_update.return_value = [{"add_update": True, "update": "new update"}]

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    updater.update("user1", "session1", conversation_history, db, used_engram_ids=["event1"])

    db.refresh(event)
    assert event.reinforcement_count == 3


def test_decay_applied_after_update(db, mock_llm, mock_embeddings, config):
    from datetime import datetime, timezone, timedelta

    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["old update"],
        relevance_score=1.0,
        last_decay_applied_at=two_hours_ago,
    )
    db.add(event)
    db.commit()

    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.detect_drift.return_value = ("update_existing", "no drift")
    llm_ops.extract_event_update.return_value = [{"add_update": True, "update": "new update"}]

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    updater.update("user1", "session1", conversation_history, db, used_engram_ids=["event1"])

    db.refresh(event)
    # Should have decayed
    assert event.relevance_score < 1.0


def test_returned_dict_contains_updated_working_state(db, mock_llm, mock_embeddings, config):
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["old update"],
        relevance_score=1.0,
    )
    db.add(event)
    db.commit()

    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.detect_drift.return_value = ("update_existing", "no drift")
    llm_ops.extract_event_update.return_value = [{"add_update": True, "update": "new update"}]

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    result = updater.update("user1", "session1", conversation_history, db, used_engram_ids=["event1"])

    assert "working_state" in result
    assert "event_id" in result
    assert result["event_id"] == "event1"


def test_path_b_create_when_llm_says_should_create(db, mock_llm, mock_embeddings, config):
    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=[],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.should_create_new_event.return_value = (True, "should create")
    llm_ops.generate_new_event.return_value = {
        "core_intent": "new intent",
        "updates": ["new update"]
    }

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    updater.update("user1", "session1", conversation_history, db)

    # Should have created an event
    events = db.query(Engram).filter(Engram.user_id == "user1").all()
    assert len(events) == 1
    assert events[0].core_intent == "new intent"


def test_path_b_create_new_event_added_to_active(db, mock_llm, mock_embeddings, config):
    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=[],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.should_create_new_event.return_value = (True, "should create")
    llm_ops.generate_new_event.return_value = {
        "core_intent": "new intent",
        "updates": ["new update"]
    }

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    result = updater.update("user1", "session1", conversation_history, db)

    # Check working state was updated
    assert len(result["working_state"]["active_event_uuids"]) == 1


def test_path_b_ets_when_llm_says_no_create(db, mock_llm, mock_embeddings, config):
    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=[],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.should_create_new_event.return_value = (False, "no create")
    llm_ops.maybe_append_to_ets.return_value = (True, "test trace")

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    updater.update("user1", "session1", conversation_history, db)

    # Should have called maybe_append_to_ets
    llm_ops.maybe_append_to_ets.assert_called_once()


def test_path_b_ets_trace_appended(db, mock_llm, mock_embeddings, config):
    from hippomem.memory.traces.service import get_traces

    WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=[],
        recent_dormant_uuids=[],
    )

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.should_create_new_event.return_value = (False, "no create")
    llm_ops.maybe_append_to_ets.return_value = (True, "test trace")

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    updater.update("user1", "session1", conversation_history, db)

    traces = get_traces("user1", "session1", db)
    assert len(traces) == 1
    assert traces[0] == "test trace"


def test_after_creating_4th_event_one_demoted_to_dormant(db, mock_llm, mock_embeddings):
    config = MemoryConfig(max_active_events=3)

    # Create 3 existing events
    for i in range(3):
        event = Engram(
            user_id="user1",
            engram_id=f"event{i}",
            core_intent=f"intent{i}",
            updates=[f"update{i}"],
            relevance_score=1.0,
        )
        db.add(event)

    working_state = WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event0", "event1", "event2"],
        recent_dormant_uuids=[],
    )

    # Persist working state so updater.update() loads it from DB
    WorkingState.persist(db, "user1", "session1", working_state)
    db.commit()

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.should_create_new_event.return_value = (True, "should create")
    llm_ops.generate_new_event.return_value = {
        "core_intent": "new intent",
        "updates": ["new update"]
    }

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    result = updater.update("user1", "session1", conversation_history, db)

    # Should have 3 active, 1 dormant
    assert len(result["working_state"]["active_event_uuids"]) == 3
    assert len(result["working_state"]["recent_dormant_uuids"]) == 1


def test_demoted_event_uuid_moves_to_recent_dormant(db, mock_llm, mock_embeddings):
    config = MemoryConfig(max_active_events=3)

    # Create 3 existing events
    for i in range(3):
        event = Engram(
            user_id="user1",
            engram_id=f"event{i}",
            core_intent=f"intent{i}",
            updates=[f"update{i}"],
            relevance_score=1.0,
        )
        db.add(event)

    working_state = WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event0", "event1", "event2"],
        recent_dormant_uuids=[],
    )

    # Persist working state so updater.update() loads it from DB
    WorkingState.persist(db, "user1", "session1", working_state)
    db.commit()

    llm_ops = MagicMock(spec=EpisodicLLMOps)
    llm_ops.should_create_new_event.return_value = (True, "should create")
    llm_ops.generate_new_event.return_value = {
        "core_intent": "new intent",
        "updates": ["new update"]
    }

    updater = MemoryEncoder(llm_ops, mock_embeddings, config=config)

    conversation_history = [("user msg", "agent response")]
    result = updater.update("user1", "session1", conversation_history, db)

    # One of the original events should be in dormant
    dormant = result["working_state"]["recent_dormant_uuids"]
    active = result["working_state"]["active_event_uuids"]
    assert len(dormant) == 1
    assert dormant[0] in ["event0", "event1", "event2"]
    assert dormant[0] not in active

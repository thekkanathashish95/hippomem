"""
Test: WorkingState.load() returns None for non-existent user
Test: WorkingState.load_or_create() creates an empty state on first call
Test: WorkingState.load_or_create() returns same state on second call (no duplicate)
Test: WorkingState.persist() updates active_event_uuids
Test: (user_id, session_id) uniqueness — persisting twice upserts, not duplicates
Test: session_id=None and session_id="session1" are different scopes
"""
from hippomem.models.working_state import WorkingState
from hippomem.schemas.working_state import WorkingStateData


def test_load_non_existent_user(db):
    data = WorkingState.load(db, "user1", "session1")
    assert data is None


def test_load_or_create_creates_empty_state(db):
    data = WorkingState.load_or_create(db, "user1", "session1")
    assert data.active_event_uuids == []
    assert data.recent_dormant_uuids == []


def test_load_or_create_returns_same_state(db):
    data1 = WorkingState.load_or_create(db, "user1", "session1")
    data2 = WorkingState.load_or_create(db, "user1", "session1")
    assert data1.working_state_id == data2.working_state_id


def test_persist_updates_active_event_uuids(db):
    data = WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1", "event2"],
        recent_dormant_uuids=[],
    )
    WorkingState.persist(db, "user1", "session1", data)

    loaded = WorkingState.load(db, "user1", "session1")
    assert loaded.active_event_uuids == ["event1", "event2"]


def test_uniqueness_upserts_not_duplicates(db):
    data1 = WorkingStateData(
        working_state_id="test1",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )
    data2 = WorkingStateData(
        working_state_id="test2",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event2"],
        recent_dormant_uuids=[],
    )

    WorkingState.persist(db, "user1", "session1", data1)
    WorkingState.persist(db, "user1", "session1", data2)  # upsert

    loaded = WorkingState.load(db, "user1", "session1")
    assert loaded.active_event_uuids == ["event2"]  # second one wins


def test_session_id_none_vs_session_scopes(db):
    data1 = WorkingStateData(
        working_state_id="global",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["global_event"],
        recent_dormant_uuids=[],
    )
    data2 = WorkingStateData(
        working_state_id="session",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["session_event"],
        recent_dormant_uuids=[],
    )

    WorkingState.persist(db, "user1", None, data1)
    WorkingState.persist(db, "user1", "session1", data2)

    global_data = WorkingState.load(db, "user1", None)
    session_data = WorkingState.load(db, "user1", "session1")

    assert global_data.active_event_uuids == ["global_event"]
    assert session_data.active_event_uuids == ["session_event"]

"""
Test: append_trace adds a trace
Test: get_traces returns only traces for that user_id+session_id
Test: get_traces with session_id=None only returns global traces
Test: FIFO eviction — when at capacity (max_size=3), oldest trace is dropped on append
Test: copy_traces creates copies under new scope
"""
from hippomem.memory.traces.service import (
    append_trace,
    get_traces,
    copy_traces,
)


def test_append_trace_adds_trace(db):
    append_trace("user1", "session1", "test content", db)
    traces = get_traces("user1", "session1", db)
    assert len(traces) == 1
    assert traces[0] == "test content"


def test_get_traces_user_session_scope(db):
    append_trace("user1", "session1", "content1", db)
    append_trace("user1", "session2", "content2", db)
    append_trace("user2", "session1", "content3", db)

    traces1 = get_traces("user1", "session1", db)
    assert len(traces1) == 1
    assert traces1[0] == "content1"

    traces2 = get_traces("user1", "session2", db)
    assert len(traces2) == 1
    assert traces2[0] == "content2"


def test_get_traces_global_scope(db):
    append_trace("user1", None, "global content", db)
    append_trace("user1", "session1", "session content", db)

    global_traces = get_traces("user1", None, db)
    assert len(global_traces) == 1
    assert global_traces[0] == "global content"


def test_fifo_eviction(db):
    # Add 3 traces (capacity=8, but test with 3)
    append_trace("user1", "session1", "first", db, max_size=3)
    append_trace("user1", "session1", "second", db, max_size=3)
    append_trace("user1", "session1", "third", db, max_size=3)
    traces = get_traces("user1", "session1", db)
    assert len(traces) == 3

    # Add fourth, should evict first
    append_trace("user1", "session1", "fourth", db, max_size=3)
    traces = get_traces("user1", "session1", db)
    assert len(traces) == 3
    assert "first" not in traces
    assert "fourth" in traces



def test_copy_traces(db):
    append_trace("user1", "session1", "content1", db)
    append_trace("user1", "session1", "content2", db)

    copied = copy_traces("user1", "session1", "user2", "session2", db)
    assert copied == 2

    traces = get_traces("user2", "session2", db)
    assert len(traces) == 2
    assert "content1" in traces
    assert "content2" in traces

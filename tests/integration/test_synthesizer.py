"""
Test: C1 CONTINUE: mock RetrieverLLMOps.check_continuation returns CONTINUE with confidence 0.9
    → synthesize() is called with only that active event
    → C3 FAISS search is NOT called
    → RecallResult.context is non-empty

Test (C1 SHIFT): mock check_continuation returns SHIFT
    → goes to C2 LocalScanRanker

Test (C2 high confidence): mock LocalScanRanker returns score=0.8 (above threshold)
    → synthesize() called with C2 results
    → C3 FAISS search is NOT triggered

Test (C2 low confidence): mock LocalScanRanker returns score=0.4 (below threshold)
    → falls through to C3

Test (C3): mock LongTermRetriever.retrieve returns 2 events
    → synthesize() called with C2 + C3 combined events

Test: empty memory (no active events) skips C1, goes to C2/C3
Test: completely empty DB (no events at all) returns empty context

Test: synthesize() returns dict with synthesized_context, used_event_uuids, reasoning keys
Test: used_event_uuids matches the events the mock LLM said it used
"""
from unittest.mock import MagicMock, patch
from hippomem.decoder.synthesizer import ContextSynthesizer
from hippomem.decoder.schemas import ContinuationResult
from hippomem.decoder.long_term import LongTermResult
from hippomem.models.engram import Engram
from hippomem.schemas.working_state import WorkingStateData
from hippomem.models.working_state import WorkingState


def test_c1_continue_uses_only_active_event(db, mock_llm, mock_embeddings, config):
    # Create active event
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["update"],
        relevance_score=1.0,
    )
    db.add(event)

    # Set working state
    working_state = WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )
    WorkingState.persist(db, "user1", "session1", working_state)

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    # Mock C1 to return CONTINUE
    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.decoder_llm_ops, 'synthesize') as mock_synth:

        mock_c1.return_value = ContinuationResult(decision="CONTINUE", confidence=0.9, reasoning="test")
        mock_synth.return_value = {
            "synthesized_context": "test context",
            "used_event_uuids": ["event1"],
            "reasoning": "test reasoning"
        }

        synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        # Should call synthesize with only the active event
        mock_synth.assert_called_once()
        call_args = mock_synth.call_args[0]
        events = call_args[0]
        assert len(events) == 1
        assert events[0]["event_uuid"] == "event1"


def test_c1_shift_goes_to_c2(db, mock_llm, mock_embeddings, config):
    # Create active event
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["update"],
        relevance_score=1.0,
    )
    db.add(event)

    working_state = WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )
    WorkingState.persist(db, "user1", "session1", working_state)

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.local_scan, 'scan_and_rank') as mock_c2:

        mock_c1.return_value = ContinuationResult(decision="SHIFT", confidence=0.5, reasoning="test")
        mock_c2.return_value = MagicMock(high_confidence=True, events=[{"event_uuid": "event1"}])

        synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        # Should call C2
        mock_c2.assert_called_once()


def test_c2_high_confidence_no_c3(db, mock_llm, mock_embeddings, config):
    event = Engram(
        user_id="user1", engram_id="event1",
        core_intent="test intent", updates=[], relevance_score=1.0,
    )
    db.add(event)
    WorkingState.persist(db, "user1", "session1", WorkingStateData(
        working_state_id="test", last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"], recent_dormant_uuids=[],
    ))

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.local_scan, 'scan_and_rank') as mock_c2, \
         patch.object(synthesizer.long_term_retriever, 'retrieve') as mock_c3, \
         patch.object(synthesizer.decoder_llm_ops, 'synthesize') as mock_synth:

        mock_c1.return_value = ContinuationResult(decision="SHIFT", confidence=0.5, reasoning="test")
        mock_c2.return_value = MagicMock(high_confidence=True, events=[{"event_uuid": "event1"}])
        mock_synth.return_value = {
            "synthesized_context": "test context",
            "used_event_uuids": ["event1"],
            "reasoning": "test reasoning"
        }

        synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        # Should NOT call C3
        mock_c3.assert_not_called()
        # Should call synthesize
        mock_synth.assert_called_once()


def test_c2_low_confidence_calls_c3(db, mock_llm, mock_embeddings, config):
    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.local_scan, 'scan_and_rank') as mock_c2, \
         patch.object(synthesizer.long_term_retriever, 'retrieve') as mock_c3:

        mock_c1.return_value = ContinuationResult(decision="SHIFT", confidence=0.5, reasoning="test")
        mock_c2.return_value = MagicMock(high_confidence=False, events=[{"event_uuid": "event1"}])
        mock_c3.return_value = LongTermResult(events=[{"event_uuid": "event2"}, {"event_uuid": "event3"}])

        synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        # Should call C3
        mock_c3.assert_called_once()


def test_c3_returns_combined_events(db, mock_llm, mock_embeddings, config):
    event = Engram(
        user_id="user1", engram_id="event1",
        core_intent="test intent", updates=[], relevance_score=1.0,
    )
    db.add(event)
    WorkingState.persist(db, "user1", "session1", WorkingStateData(
        working_state_id="test", last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"], recent_dormant_uuids=[],
    ))

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.local_scan, 'scan_and_rank') as mock_c2, \
         patch.object(synthesizer.long_term_retriever, 'retrieve') as mock_c3, \
         patch.object(synthesizer.decoder_llm_ops, 'synthesize') as mock_synth:

        mock_c1.return_value = ContinuationResult(decision="SHIFT", confidence=0.5, reasoning="test")
        mock_c2.return_value = MagicMock(high_confidence=False, events=[{"event_uuid": "event1"}])
        mock_c3.return_value = LongTermResult(events=[{"event_uuid": "event2"}, {"event_uuid": "event3"}])
        mock_synth.return_value = {
            "synthesized_context": "test context",
            "used_event_uuids": ["event1", "event2", "event3"],
            "reasoning": "test reasoning"
        }

        synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        # Should call synthesize with combined events
        mock_synth.assert_called_once()
        call_args = mock_synth.call_args[0]
        events = call_args[0]
        # Should have C2 event (event1) + C3 events (event2, event3)
        assert len(events) >= 3


def test_empty_memory_skips_c1(db, mock_llm, mock_embeddings, config):
    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.local_scan, 'scan_and_rank') as mock_c2:

        synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        # Should NOT call C1 (no active events)
        mock_c1.assert_not_called()
        # Should call C2
        mock_c2.assert_called_once()


def test_completely_empty_db_returns_empty_context(db, mock_llm, mock_embeddings, config):
    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    result = synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

    assert result["synthesized_context"] == ""
    assert result["used_engram_ids"] == []


def test_synthesize_returns_correct_keys(db, mock_llm, mock_embeddings, config):
    # Create active event
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["update"],
        relevance_score=1.0,
    )
    db.add(event)

    working_state = WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )
    WorkingState.persist(db, "user1", "session1", working_state)

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.decoder_llm_ops, 'synthesize') as mock_synth:

        mock_c1.return_value = ContinuationResult(decision="CONTINUE", confidence=0.9, reasoning="test")
        mock_synth.return_value = {
            "synthesized_context": "test context",
            "used_event_uuids": ["event1"],
            "reasoning": "test reasoning"
        }

        result = synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        assert "synthesized_context" in result
        assert "used_event_uuids" in result
        assert "reasoning" in result


def test_used_event_uuids_matches_mock(db, mock_llm, mock_embeddings, config):
    # Create active event
    event = Engram(
        user_id="user1",
        engram_id="event1",
        core_intent="test intent",
        updates=["update"],
        relevance_score=1.0,
    )
    db.add(event)

    working_state = WorkingStateData(
        working_state_id="test",
        last_updated="2023-01-01T00:00:00Z",
        active_event_uuids=["event1"],
        recent_dormant_uuids=[],
    )
    WorkingState.persist(db, "user1", "session1", working_state)

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)

    with patch.object(synthesizer.decoder_llm_ops, 'check_continuation') as mock_c1, \
         patch.object(synthesizer.decoder_llm_ops, 'synthesize') as mock_synth:

        mock_c1.return_value = ContinuationResult(decision="CONTINUE", confidence=0.9, reasoning="test")
        expected_uuids = ["event1"]
        mock_synth.return_value = {
            "synthesized_context": "test context",
            "used_engram_ids": expected_uuids,
            "reasoning": "test reasoning"
        }

        result = synthesizer.synthesize("user1", "session1", "test message", [("user", "assistant")], db)

        assert result["used_engram_ids"] == expected_uuids

"""
Integration tests for SelfExtractor.extract_and_accumulate() and consolidate_self_memory().
"""
from unittest.mock import MagicMock

from hippomem.memory.self.extractor import SelfExtractor
from hippomem.memory.self.llm_ops import SelfLLMOps
from hippomem.memory.self.schemas import SelfExtractionResult, ExtractedSelfCandidate
from hippomem.consolidator.service import consolidate_self_memory
from hippomem.consolidator.llm_ops import ConsolidationLLMOps
from hippomem.models.self_trait import SelfTrait
from hippomem.models.engram import Engram, EngramKind


def test_extract_and_accumulate_no_candidates_skips_db(db, mock_llm):
    """LLM returns empty candidates → no SelfTrait rows written."""
    mock_llm.chat_structured.return_value = SelfExtractionResult(candidates=[])

    llm_ops = SelfLLMOps(mock_llm)
    extractor = SelfExtractor(llm_ops)

    extractor.extract_and_accumulate(
        user_id="user1",
        user_message="Hello",
        conversation_history=[("Hello", "Hi")],
        db=db,
    )

    count = db.query(SelfTrait).filter(SelfTrait.user_id == "user1").count()
    assert count == 0


def test_extract_and_accumulate_creates_trait_on_first_observation(db, mock_llm):
    """LLM returns 1 candidate → SelfTrait row created, is_active=False."""
    mock_llm.chat_structured.return_value = SelfExtractionResult(
        candidates=[
            ExtractedSelfCandidate(
                category="stable_attribute",
                key="occupation",
                value="software engineer",
                action="new",
                confidence_estimate=0.9,
            ),
        ]
    )

    llm_ops = SelfLLMOps(mock_llm)
    extractor = SelfExtractor(llm_ops)

    extractor.extract_and_accumulate(
        user_id="user1",
        user_message="I'm a software engineer",
        conversation_history=[("I'm a software engineer", "Nice")],
        db=db,
    )

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1",
        SelfTrait.key == "occupation",
    ).first()
    assert row is not None
    assert row.is_active is False
    assert row.evidence_count == 1


def test_extract_and_accumulate_activates_on_second_observation(db, mock_llm):
    """Call twice with same key → is_active=True after second call."""
    mock_llm.chat_structured.return_value = SelfExtractionResult(
        candidates=[
            ExtractedSelfCandidate(
                category="goal",
                key="career_goal",
                value="building hippomem",
                action="confirm",
                confidence_estimate=0.8,
            ),
        ]
    )

    llm_ops = SelfLLMOps(mock_llm)
    extractor = SelfExtractor(llm_ops)

    extractor.extract_and_accumulate(
        user_id="user1",
        user_message="I want to build hippomem",
        conversation_history=[("I want to build hippomem", "Cool")],
        db=db,
    )
    extractor.extract_and_accumulate(
        user_id="user1",
        user_message="Hippomem is my main project",
        conversation_history=[("I want to build hippomem", "Cool"), ("Hippomem is my main project", "Got it")],
        db=db,
    )

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1",
        SelfTrait.key == "career_goal",
    ).first()
    assert row is not None
    assert row.is_active is True
    assert row.evidence_count == 2


def test_extract_and_accumulate_seeds_existing_traits_into_llm(db, mock_llm):
    """Verifies llm_ops is called with existing trait values + evidence counts as context."""
    # Pre-seed a trait with value and evidence_count
    t = SelfTrait(
        user_id="user1",
        category="stable_attribute",
        key="occupation",
        value="engineer",
        evidence_count=3,
    )
    db.add(t)
    db.commit()

    mock_llm.chat_structured.return_value = SelfExtractionResult(candidates=[])

    llm_ops = SelfLLMOps(mock_llm)
    extractor = SelfExtractor(llm_ops)

    extractor.extract_and_accumulate(
        user_id="user1",
        user_message="I code a lot",
        conversation_history=[("I code a lot", "OK")],
        db=db,
    )

    mock_llm.chat_structured.assert_called_once()
    call_kwargs = mock_llm.chat_structured.call_args
    user_content = call_kwargs[1]["messages"][1]["content"]
    # Prompt should contain trait value and evidence count (not just key names)
    assert "occupation" in user_content
    assert "engineer" in user_content
    assert "3" in user_content


def test_consolidate_self_memory_creates_persona_engram(db, mock_llm):
    """Active traits → persona Engram created with summary_text."""
    t1 = SelfTrait(
        user_id="user1",
        category="goal",
        key="career_goal",
        value="building hippomem",
        is_active=True,
        confidence_score=0.8,
    )
    t2 = SelfTrait(
        user_id="user1",
        category="preference",
        key="response_format",
        value="concise",
        is_active=True,
        confidence_score=0.7,
    )
    db.add_all([t1, t2])
    db.commit()

    mock_llm.chat_structured.return_value = MagicMock(identity_summary="A builder who likes concise answers")

    llm_ops = ConsolidationLLMOps(mock_llm)
    result = consolidate_self_memory("user1", db, llm_ops, min_confidence=0.5)

    assert result is True
    persona = db.query(Engram).filter(
        Engram.user_id == "user1",
        Engram.engram_kind == EngramKind.PERSONA.value,
    ).first()
    assert persona is not None
    assert persona.summary_text == "A builder who likes concise answers"


def test_consolidate_self_memory_skips_if_hash_unchanged(db, mock_llm):
    """Call twice, same traits → LLM called only once."""
    t = SelfTrait(
        user_id="user1",
        category="goal",
        key="career_goal",
        value="building hippomem",
        is_active=True,
        confidence_score=0.8,
    )
    db.add(t)
    db.commit()

    mock_llm.chat_structured.return_value = MagicMock(identity_summary="A builder")

    llm_ops = ConsolidationLLMOps(mock_llm)
    consolidate_self_memory("user1", db, llm_ops, min_confidence=0.5)
    first_call_count = mock_llm.chat_structured.call_count

    consolidate_self_memory("user1", db, llm_ops, min_confidence=0.5)
    assert mock_llm.chat_structured.call_count == first_call_count


def test_consolidate_self_memory_updates_on_new_trait(db, mock_llm):
    """New trait activates → new hash → LLM called again."""
    t1 = SelfTrait(
        user_id="user1",
        category="goal",
        key="career_goal",
        value="building hippomem",
        is_active=True,
        confidence_score=0.8,
    )
    db.add(t1)
    db.commit()

    mock_llm.chat_structured.return_value = MagicMock(identity_summary="A builder")

    llm_ops = ConsolidationLLMOps(mock_llm)
    consolidate_self_memory("user1", db, llm_ops, min_confidence=0.5)
    first_call_count = mock_llm.chat_structured.call_count

    # Add second active trait
    t2 = SelfTrait(
        user_id="user1",
        category="preference",
        key="response_format",
        value="concise",
        is_active=True,
        confidence_score=0.7,
    )
    db.add(t2)
    db.commit()

    consolidate_self_memory("user1", db, llm_ops, min_confidence=0.5)
    assert mock_llm.chat_structured.call_count > first_call_count

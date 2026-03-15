"""
Integration tests for SelfExtractor.extract_and_accumulate(), consolidate_self_memory(),
and ContextSynthesizer._load_self_profile().
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from hippomem.memory.self.extractor import SelfExtractor
from hippomem.memory.self.llm_ops import SelfLLMOps
from hippomem.memory.self.schemas import SelfExtractionResult, ExtractedSelfCandidate
from hippomem.consolidator.service import consolidate_self_memory
from hippomem.consolidator.llm_ops import ConsolidationLLMOps
from hippomem.decoder.synthesizer import ContextSynthesizer
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


def test_extract_and_accumulate_high_confidence_activates_immediately(db, mock_llm):
    """High confidence candidate (0.9) → is_active=True on first observation."""
    mock_llm.chat_structured.return_value = SelfExtractionResult(
        candidates=[
            ExtractedSelfCandidate(
                category="stable_attribute",
                key="occupation",
                value="software engineer",
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
    assert row.is_active is True
    assert row.evidence_count == 1


def test_extract_and_accumulate_low_confidence_inactive_until_second(db, mock_llm):
    """Low confidence candidate (0.65) → is_active=False on first, True on second."""
    mock_llm.chat_structured.return_value = SelfExtractionResult(
        candidates=[
            ExtractedSelfCandidate(
                category="personality",
                key="thinking_style",
                value="first principles",
                confidence_estimate=0.65,
            ),
        ]
    )

    llm_ops = SelfLLMOps(mock_llm)
    extractor = SelfExtractor(llm_ops)

    extractor.extract_and_accumulate(
        user_id="user1",
        user_message="I like thinking from first principles",
        conversation_history=[],
        db=db,
    )

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1", SelfTrait.key == "thinking_style"
    ).first()
    assert row is not None
    assert row.is_active is False  # not yet active

    extractor.extract_and_accumulate(
        user_id="user1",
        user_message="I always reason from first principles",
        conversation_history=[],
        db=db,
    )

    db.refresh(row)
    assert row.is_active is True
    assert row.evidence_count == 2


def test_extract_and_accumulate_increments_on_second_observation(db, mock_llm):
    """Call twice with same high-confidence key → evidence_count=2, is_active=True."""
    mock_llm.chat_structured.return_value = SelfExtractionResult(
        candidates=[
            ExtractedSelfCandidate(
                category="goal",
                key="career_goal",
                value="building hippomem",
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
    assert row.value == "building hippomem"


def test_extract_and_accumulate_seeds_existing_traits_into_llm(db, mock_llm):
    """Verifies llm_ops is called with existing trait values + evidence counts as context."""
    t = SelfTrait(
        user_id="user1",
        category="stable_attribute",
        key="occupation",
        value="engineer",
        evidence_count=3,
        is_active=True,
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
    result = consolidate_self_memory("user1", db, llm_ops)

    assert result is True
    persona = db.query(Engram).filter(
        Engram.user_id == "user1",
        Engram.engram_kind == EngramKind.PERSONA.value,
    ).first()
    assert persona is not None
    assert persona.summary_text == "A builder who likes concise answers"


def test_consolidate_self_memory_excludes_inactive_traits(db, mock_llm):
    """Inactive traits are not included — persona generation returns False when no active traits."""
    t = SelfTrait(
        user_id="user1",
        category="personality",
        key="thinking_style",
        value="first principles",
        is_active=False,  # not yet activated
        confidence_score=0.65,
    )
    db.add(t)
    db.commit()

    llm_ops = ConsolidationLLMOps(mock_llm)
    result = consolidate_self_memory("user1", db, llm_ops)

    assert result is False
    mock_llm.chat_structured.assert_not_called()


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
    consolidate_self_memory("user1", db, llm_ops)
    first_call_count = mock_llm.chat_structured.call_count

    consolidate_self_memory("user1", db, llm_ops)
    assert mock_llm.chat_structured.call_count == first_call_count


def test_consolidate_self_memory_updates_on_new_trait(db, mock_llm):
    """New active trait → new hash → LLM called again."""
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
    consolidate_self_memory("user1", db, llm_ops)
    first_call_count = mock_llm.chat_structured.call_count

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

    consolidate_self_memory("user1", db, llm_ops)
    assert mock_llm.chat_structured.call_count > first_call_count


# ── _load_self_profile tests ──────────────────────────────────────────────────

def test_load_self_profile_returns_persona_when_all_traits_current(db, mock_llm, mock_embeddings, config):
    """Persona exists and all traits are older than persona.updated_at → source='persona'."""
    config.enable_self_memory = True
    persona_time = datetime.now(timezone.utc)

    persona = Engram(
        user_id="user1",
        engram_id="persona-1",
        engram_kind=EngramKind.PERSONA.value,
        core_intent="self_profile",
        summary_text="A builder who prefers concise answers.",
        updated_at=persona_time,
    )
    db.add(persona)

    # Trait observed before persona was written
    trait = SelfTrait(
        user_id="user1",
        category="goal",
        key="career_goal",
        value="building hippomem",
        is_active=True,
        last_observed_at=persona_time - timedelta(hours=1),
    )
    db.add(trait)
    db.commit()

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)
    profile, source = synthesizer._load_self_profile("user1", db)

    assert source == "persona"
    assert profile == "A builder who prefers concise answers."


def test_load_self_profile_appends_pending_traits_when_persona_stale(db, mock_llm, mock_embeddings, config):
    """New trait observed after persona.updated_at → source='persona+pending', both sections present."""
    config.enable_self_memory = True
    persona_time = datetime.now(timezone.utc) - timedelta(hours=1)

    persona = Engram(
        user_id="user1",
        engram_id="persona-1",
        engram_kind=EngramKind.PERSONA.value,
        core_intent="self_profile",
        summary_text="A builder who prefers concise answers.",
        updated_at=persona_time,
    )
    db.add(persona)

    # Old trait — already reflected in persona
    old_trait = SelfTrait(
        user_id="user1",
        category="goal",
        key="career_goal",
        value="building hippomem",
        is_active=True,
        last_observed_at=persona_time - timedelta(hours=1),
    )
    # New trait — observed after last consolidation
    new_trait = SelfTrait(
        user_id="user1",
        category="preference",
        key="greeting_style",
        value="never greet with good morning",
        is_active=True,
        last_observed_at=datetime.now(timezone.utc),
    )
    db.add_all([old_trait, new_trait])
    db.commit()

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)
    profile, source = synthesizer._load_self_profile("user1", db)

    assert source == "persona+pending"
    assert "A builder who prefers concise answers." in profile
    assert "pending consolidation" in profile
    assert "greeting_style" in profile
    # old trait not duplicated in pending block
    assert profile.count("career_goal") == 0


def test_load_self_profile_falls_back_to_traits_when_no_persona(db, mock_llm, mock_embeddings, config):
    """No Persona Engram yet → falls back to raw trait injection, source='traits'."""
    config.enable_self_memory = True

    trait = SelfTrait(
        user_id="user1",
        category="goal",
        key="career_goal",
        value="building hippomem",
        is_active=True,
        last_observed_at=datetime.now(timezone.utc),
    )
    db.add(trait)
    db.commit()

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)
    profile, source = synthesizer._load_self_profile("user1", db)

    assert source == "traits"
    assert "career_goal" in profile


def test_load_self_profile_returns_none_when_disabled(db, mock_llm, mock_embeddings, config):
    """enable_self_memory=False → (None, 'none') regardless of DB state."""
    config.enable_self_memory = False

    synthesizer = ContextSynthesizer(mock_llm, mock_embeddings, config)
    profile, source = synthesizer._load_self_profile("user1", db)

    assert profile is None
    assert source == "none"

"""
Unit tests for memory/self/service.py.
Pure Python + SQLAlchemy — uses db fixture, no LLM mocking.
"""
from hippomem.memory.self.service import (
    accumulate_traits,
    get_active_traits,
    get_existing_traits,
    compute_traits_hash,
    format_traits_for_injection,
)
from hippomem.models.self_trait import SelfTrait
from hippomem.memory.self.schemas import ExtractedSelfCandidate


def test_accumulate_traits_new_trait_not_active(db):
    """evidence_count=1, is_active=False, confidence = 0.6 * model_confidence."""
    candidates = [
        ExtractedSelfCandidate(
            category="stable_attribute",
            key="occupation",
            value="software engineer",
            action="new",
            confidence_estimate=0.9,
        ),
    ]
    accumulate_traits("user1", candidates, db)
    db.commit()

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1",
        SelfTrait.category == "stable_attribute",
        SelfTrait.key == "occupation",
    ).first()
    assert row is not None
    assert row.evidence_count == 1
    assert row.is_active is False
    assert abs(row.confidence_score - 0.9 * 0.6) < 0.001


def test_accumulate_traits_second_observation_activates(db):
    """evidence_count becomes 2, is_active=True."""
    candidates = [
        ExtractedSelfCandidate(
            category="goal",
            key="career_goal",
            value="building hippomem",
            action="new",
            confidence_estimate=0.8,
        ),
    ]
    accumulate_traits("user1", candidates, db)
    db.commit()

    accumulate_traits("user1", candidates, db)
    db.commit()

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1",
        SelfTrait.category == "goal",
        SelfTrait.key == "career_goal",
    ).first()
    assert row is not None
    assert row.evidence_count == 2
    assert row.is_active is True


def test_accumulate_traits_confidence_clamped_at_one(db):
    """Repeated accumulation stays <= 1.0."""
    candidates = [
        ExtractedSelfCandidate(
            category="preference",
            key="response_format",
            value="concise",
            action="confirm",
            confidence_estimate=1.0,
        ),
    ]
    for _ in range(15):
        accumulate_traits("user1", candidates, db)
        db.commit()

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1",
        SelfTrait.category == "preference",
        SelfTrait.key == "response_format",
    ).first()
    assert row is not None
    assert row.confidence_score <= 1.0


def test_get_existing_traits_returns_full_state(db):
    """Returns list of {category, key, value, evidence_count} dicts."""
    for cat, key, val, count in [
        ("stable_attribute", "occupation", "software engineer", 3),
        ("goal", "career_goal", "building hippomem", 1),
    ]:
        t = SelfTrait(
            user_id="user1",
            category=cat,
            key=key,
            value=val,
            evidence_count=count,
        )
        db.add(t)
    db.commit()

    result = get_existing_traits("user1", db)
    assert len(result) == 2
    by_key = {r["key"]: r for r in result}
    assert by_key["occupation"]["value"] == "software engineer"
    assert by_key["occupation"]["evidence_count"] == 3
    assert by_key["career_goal"]["category"] == "goal"


def test_accumulate_traits_update_stores_previous_value(db):
    """action=update → previous_value preserved, new value written."""
    first = [ExtractedSelfCandidate(
        category="stable_attribute", key="occupation",
        value="junior engineer", action="new", confidence_estimate=0.8,
    )]
    accumulate_traits("user1", first, db)
    db.commit()

    second = [ExtractedSelfCandidate(
        category="stable_attribute", key="occupation",
        value="staff engineer", action="update", confidence_estimate=0.9,
    )]
    accumulate_traits("user1", second, db)
    db.commit()

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1", SelfTrait.key == "occupation"
    ).first()
    assert row.value == "staff engineer"
    assert row.previous_value == "junior engineer"


def test_accumulate_traits_confirm_does_not_overwrite_value(db):
    """action=confirm → value unchanged, evidence strengthened."""
    first = [ExtractedSelfCandidate(
        category="stable_attribute", key="occupation",
        value="software engineer", action="new", confidence_estimate=0.8,
    )]
    accumulate_traits("user1", first, db)
    db.commit()

    confirm = [ExtractedSelfCandidate(
        category="stable_attribute", key="occupation",
        value="software engineer",  # same value
        action="confirm", confidence_estimate=0.9,
    )]
    accumulate_traits("user1", confirm, db)
    db.commit()

    row = db.query(SelfTrait).filter(
        SelfTrait.user_id == "user1", SelfTrait.key == "occupation"
    ).first()
    assert row.value == "software engineer"
    assert row.previous_value is None  # no change recorded
    assert row.evidence_count == 2


def test_get_active_traits_filters_inactive(db):
    """Only is_active=True traits returned."""
    t1 = SelfTrait(
        user_id="user1",
        category="stable_attribute",
        key="active_trait",
        value="active",
        is_active=True,
    )
    t2 = SelfTrait(
        user_id="user1",
        category="goal",
        key="inactive_trait",
        value="inactive",
        is_active=False,
    )
    db.add_all([t1, t2])
    db.commit()

    result = get_active_traits("user1", db)
    assert len(result) == 1
    assert result[0].key == "active_trait"


def test_compute_traits_hash_is_stable(db):
    """Same traits in same order → same hash."""
    traits = [
        SelfTrait(user_id="u", category="a", key="k1", value="v1"),
        SelfTrait(user_id="u", category="b", key="k2", value="v2"),
    ]
    h1 = compute_traits_hash(traits)
    h2 = compute_traits_hash(traits)
    assert h1 == h2


def test_compute_traits_hash_changes_on_trait_change(db):
    """Different traits → different hash."""
    traits1 = [SelfTrait(user_id="u", category="a", key="k1", value="v1")]
    traits2 = [SelfTrait(user_id="u", category="a", key="k1", value="v2")]
    h1 = compute_traits_hash(traits1)
    h2 = compute_traits_hash(traits2)
    assert h1 != h2


def test_format_traits_for_injection_groups_by_category(db):
    """Output contains category headings and values."""
    traits = [
        SelfTrait(user_id="u", category="goal", key="career_goal", value="building hippomem"),
        SelfTrait(user_id="u", category="preference", key="response_format", value="concise"),
    ]
    result = format_traits_for_injection(traits)
    assert "[Goals]" in result
    assert "career_goal: building hippomem" in result
    assert "[Preferences]" in result
    assert "response_format: concise" in result


def test_format_traits_empty_list_returns_empty_string():
    """Empty list returns empty string."""
    result = format_traits_for_injection([])
    assert result == ""

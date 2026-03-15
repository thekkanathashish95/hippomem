"""Service functions for self trait accumulation and retrieval."""
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict

from sqlalchemy.orm import Session

from hippomem.models.self_trait import SelfTrait
from hippomem.memory.self.schemas import ExtractedSelfCandidate

# Traits with confidence_estimate >= this threshold activate immediately on first observation.
# Below this threshold, a trait requires evidence_count >= 2 before becoming active.
HIGH_CONFIDENCE_THRESHOLD = 0.8


def get_existing_traits(user_id: str, db: Session) -> List[Dict[str, str]]:
    """
    Load active traits for a user: category, key, value, evidence_count.
    Passed to the extraction prompt so the LLM only returns traits not already
    captured here (or ones whose value has meaningfully changed).
    """
    rows = (
        db.query(SelfTrait.category, SelfTrait.key, SelfTrait.value, SelfTrait.evidence_count)
        .filter(SelfTrait.user_id == user_id, SelfTrait.is_active.is_(True))
        .all()
    )
    return [
        {"category": row.category, "key": row.key, "value": row.value, "evidence_count": row.evidence_count}
        for row in rows
    ]


def accumulate_traits(
    user_id: str,
    candidates: List[ExtractedSelfCandidate],
    db: Session,
) -> int:
    """
    Upsert SelfTrait rows from LLM-extracted candidates.
    The LLM only returns traits that are new or changed, so every candidate
    is either a fresh insert or an update to an existing value.

    Activation rule:
    - confidence_estimate >= HIGH_CONFIDENCE_THRESHOLD (0.8): activate immediately
    - below threshold: activate once evidence_count reaches 2

    Returns the number of rows upserted.
    """
    now = datetime.now(timezone.utc)
    upserted = 0
    for c in candidates:
        row = (
            db.query(SelfTrait)
            .filter(
                SelfTrait.user_id == user_id,
                SelfTrait.category == c.category,
                SelfTrait.key == c.key,
            )
            .first()
        )

        if row is None:
            row = SelfTrait(
                user_id=user_id,
                category=c.category,
                key=c.key,
                value=c.value,
                previous_value=None,
                confidence_score=c.confidence_estimate,
                evidence_count=1,
                is_active=c.confidence_estimate >= HIGH_CONFIDENCE_THRESHOLD,
                first_observed_at=now,
                last_observed_at=now,
            )
            db.add(row)
        else:
            if row.value != c.value:
                row.previous_value = row.value
                row.value = c.value
            row.confidence_score = min(1.0, row.confidence_score + 0.1 * c.confidence_estimate)
            row.evidence_count += 1
            row.last_observed_at = now
            if not row.is_active:
                row.is_active = (
                    row.evidence_count >= 2
                    or c.confidence_estimate >= HIGH_CONFIDENCE_THRESHOLD
                )
        upserted += 1
    return upserted


def get_active_traits(user_id: str, db: Session) -> List[SelfTrait]:
    """Return active traits ordered by category, then confidence descending."""
    return (
        db.query(SelfTrait)
        .filter(SelfTrait.user_id == user_id, SelfTrait.is_active)
        .order_by(SelfTrait.category, SelfTrait.confidence_score.desc())
        .all()
    )


def compute_traits_hash(traits: List[SelfTrait]) -> str:
    """
    Stable hash of active trait content. Used by consolidate() to skip
    redundant LLM calls when traits haven't changed since last consolidation.
    """
    canonical = sorted(
        [{"category": t.category, "key": t.key, "value": t.value} for t in traits],
        key=lambda x: (x["category"], x["key"]),
    )
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def format_traits_for_injection(traits: List[SelfTrait]) -> str:
    """
    Format active traits as a structured block for direct decoder injection.
    Used as fallback when no persona Engram exists yet.

    Output example:
      [Goals] career_goal: building hippomem as a product
      [Preferences] response_format: concise with code examples
      [Stable Attributes] occupation: software engineer
    """
    if not traits:
        return ""
    lines = []
    category_label = {
        "stable_attribute": "Stable Attributes",
        "goal": "Goals",
        "personality": "Personality",
        "preference": "Preferences",
        "constraint": "Constraints",
        "project": "Projects",
        "social": "Relationships",
    }
    for trait in traits:
        label = category_label.get(
            trait.category, trait.category.replace("_", " ").title()
        )
        lines.append(f"[{label}] {trait.key}: {trait.value}")
    return "\n".join(lines)

"""Service functions for self trait accumulation and retrieval."""
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict

from sqlalchemy.orm import Session

from hippomem.models.self_trait import SelfTrait
from hippomem.memory.self.schemas import ExtractedSelfCandidate


def get_existing_traits(user_id: str, db: Session) -> List[Dict[str, str]]:
    """
    Load full trait state for a user: category, key, value, evidence_count.
    Used to seed the extraction prompt so the LLM can classify each candidate
    as new / update / confirm rather than re-extracting everything blindly.
    """
    rows = (
        db.query(SelfTrait.category, SelfTrait.key, SelfTrait.value, SelfTrait.evidence_count)
        .filter(SelfTrait.user_id == user_id)
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
) -> tuple:
    """
    Upsert SelfTrait rows based on explicit action classification from the LLM.
    Activation rule: evidence_count >= 2.
    Returns (upserted, newly_active).

    Action semantics:
      new     — insert; evidence_count=1, is_active=False (activates at evidence_count>=2)
      confirm — increment evidence_count, leave value untouched
      update  — value has changed; store previous_value before overwriting
    """
    now = datetime.now(timezone.utc)
    upserted, newly_active = 0, 0
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
            # Treat as new regardless of LLM action (no existing row to match)
            row = SelfTrait(
                user_id=user_id,
                category=c.category,
                key=c.key,
                value=c.value,
                previous_value=None,
                confidence_score=c.confidence_estimate * 0.6,
                evidence_count=1,
                is_active=False,
                first_observed_at=now,
                last_observed_at=now,
            )
            db.add(row)
            upserted += 1
        else:
            was_active = row.is_active
            if c.action == "update":
                # Value has evolved — preserve previous for traceability
                row.previous_value = row.value
                row.value = c.value
            elif c.action == "confirm":
                # Value unchanged — only strengthen evidence; don't touch value
                pass
            else:
                # Fallback for "new" with a conflicting existing row: treat as update
                row.previous_value = row.value
                row.value = c.value
            row.confidence_score = min(
                1.0, row.confidence_score + 0.1 * c.confidence_estimate
            )
            row.evidence_count += 1
            row.is_active = True  # re-activate if consolidator had demoted it
            row.last_observed_at = now
            upserted += 1
            if not was_active and row.is_active:
                newly_active += 1
    return (upserted, newly_active)


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

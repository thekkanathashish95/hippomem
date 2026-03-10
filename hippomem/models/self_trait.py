"""
SelfTrait - Durable user identity signals (goals, preferences, personality).
Extracted from conversation turns; activated when evidence_count >= 2.
"""
import uuid
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, Boolean, UniqueConstraint

from hippomem.db.base import Base


class SelfTrait(Base):
    __tablename__ = "self_traits"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)

    category = Column(String, nullable=False)
    # enum values: stable_attribute | goal | personality | preference | constraint | project | social

    key = Column(String, nullable=False)
    # normalized attribute name within category, e.g. "occupation", "response_format"
    # LLM is instructed to reuse existing keys when the trait matches

    value = Column(Text, nullable=False)
    # the trait content, e.g. "software engineer", "prefers bullet points"

    previous_value = Column(Text, nullable=True)
    # set when an update action changes an existing value; one level of history

    confidence_score = Column(Float, default=0.0)
    # accumulated LLM-estimated confidence (tracked passively, not used to gate activation)

    evidence_count = Column(Integer, default=0)
    # number of independent observations

    is_active = Column(Boolean, default=False)
    # True when evidence_count >= 2

    first_observed_at = Column(DateTime(timezone=True), nullable=True)
    last_observed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "category", "key", name="uq_self_trait"),
    )

"""Pydantic response schemas for episodic memory LLM operations."""
from typing import List, Optional, Literal

from pydantic import BaseModel, Field


class EventUpdateItem(BaseModel):
    """One update decision for a single engram: whether to add an update and any refined core intent."""

    add_update: bool = False
    update: Optional[str] = None
    refined_core_intent: Optional[str] = None


class ExtractEventUpdateResponse(BaseModel):
    """LLM response: list of per-engram update decisions, one entry per input engram."""

    updates: List[EventUpdateItem] = Field(default_factory=list)


class DetectDriftResponse(BaseModel):
    """LLM response: whether the current turn stays in the active engram or branches to a new one."""

    decision: Literal["update_existing", "create_new_branch"] = "update_existing"
    reason: Optional[str] = None


class ShouldCreateNewEventResponse(BaseModel):
    """LLM response: whether this turn warrants a new long-term engram or just an ETS trace."""

    should_create: bool = True
    reason: Optional[str] = None


class GenerateNewEventResponse(BaseModel):
    """LLM response: core_intent and initial updates for a brand-new memory engram."""

    core_intent: str = "New conversation topic"
    updates: List[str] = Field(default_factory=list)


class MaybeAppendToEtsResponse(BaseModel):
    """LLM response: whether to store a trace in the Ephemeral Trace Store and what summary to use."""

    store: bool = False
    trace_summary: Optional[str] = None

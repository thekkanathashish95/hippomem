from pydantic import BaseModel, Field
from typing import List
from sqlalchemy import TypeDecorator
from sqlalchemy.types import JSON


class WorkingStateData(BaseModel):
    """
    Working state data structure.
    EventStore is source of truth; this stores UUIDs only.
    """
    working_state_id: str = ""
    last_updated: str = ""  # ISO datetime string
    active_event_uuids: List[str] = Field(default_factory=list)
    recent_dormant_uuids: List[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class WorkingStateDataType(TypeDecorator):
    """
    SQLAlchemy type that serializes WorkingStateData to/from JSON.
    Use as: state_data = Column(WorkingStateDataType, nullable=False)
    """
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, WorkingStateData):
            return value.model_dump()
        if isinstance(value, dict):
            return WorkingStateData.model_validate(value).model_dump()
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return WorkingStateData.model_validate(value or {})
